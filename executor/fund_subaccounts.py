# Ainara AI Companion Framework Project
# Copyright (C) 2025 Rubén Gómez - khromalabs.org
#
# This file is dual-licensed under:
# 1. GNU Lesser General Public License v3.0 (LGPL-3.0)
#    (See the included LICENSE_LGPL3.txt file or look into
#    <https://www.gnu.org/licenses/lgpl-3.0.html> for details)
# 2. Commercial license
#    (Contact: rgomez@khromalabs.org for licensing options)
#
# You may use, distribute and modify this code under the terms of either license.
# This notice must be preserved in all copies or substantial portions of the code.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# Lesser General Public License for more details.

"""Move USDC between your own dYdX subaccounts, to fund position isolation.

    DRY (default): read every subaccount, print the plan, broadcast nothing.
    --broadcast:   actually send the transfers.

    Usage (executor venv, from the project root):
      $env:DYDX_MAIN_MNEMONIC = 'word word ...'
      executor\\.venv\\Scripts\\python.exe -m executor.fund_subaccounts --even
      executor\\.venv\\Scripts\\python.exe -m executor.fund_subaccounts --to 1 --amount 32
      ... add --broadcast once the printed plan is what you want.

WHY THIS NEEDS YOUR MAIN WALLET
-------------------------------
There is nothing to "create" on dYdX: a subaccount exists the moment collateral
lands in it, and `subaccountNumber` is just an index. Funding one is a MsgTransfer
between two subaccounts of the same owner.

The bot's credential cannot sign that, on purpose. Its authenticator is composed
AllOf[ signature(bot), AnyOf[MsgPlaceOrder, MsgCancelOrder], subaccount_filter,
clob_pair_filter ] — a transfer fails the message filter. That restriction is the
whole value of the permissioned-key design: a leaked bot key can place bad orders
but cannot move a dollar. So this script needs the OWNER key, once, and then you
should forget it again.

The mnemonic is read from the environment and never from ainara.yaml. That is not
pedantry: ConfigManager.save() copies the config to ainara.yaml.bak before writing,
and Orakle exposes PUT /config, so a seed placed in that file survives in a second
file after you delete it from the first.

SAFETY
------
  - Dry run by default; --broadcast is required to send anything.
  - Refuses unless the mnemonic derives the configured account address, so a wrong
    seed is caught before a signature rather than after.
  - Refuses to move collateral OUT of a subaccount holding an open position: that
    is its margin, and thinning it moves the liquidation price the wrong way.
  - Refuses transfers that would leave the source below --min-source (default 5
    USDC), so a fat-fingered amount cannot strip subaccount 0 bare.
  - Never withdraws off dYdX. Transfers only, between subaccounts you own.
"""

import argparse
import asyncio
import os
import re
import sys

import requests
from dydx_v4_client.node.client import NodeClient
from dydx_v4_client.wallet import Wallet
from v4_proto.dydxprotocol.subaccounts.subaccount_pb2 import SubaccountId

from executor.config import ExecutorConfig
from executor.venues.dydx import (INDEXER, _address_from_mnemonic, dydx_network)

# dYdX quote asset. USDC is asset id 0 and carries 6 decimals, so 1 USDC = 1e6
# quantums. Getting this wrong by 10^6 is the classic way to move the wrong amount,
# which is why nothing here takes a raw quantum figure from the caller.
USDC_ASSET_ID = 0
USDC_QUANTUMS = 1_000_000


def read_subaccounts(indexer, address):
    """Every subaccount with its collateral and open-position count."""
    r = requests.get(f"{indexer}/v4/addresses/{address}", timeout=20)
    r.raise_for_status()
    payload = r.json()
    if "subaccounts" not in payload:
        sys.exit(f"indexer returned no 'subaccounts' field: {str(payload)[:200]}")
    out = {}
    for s in payload["subaccounts"]:
        positions = {k: v for k, v in (s.get("openPerpetualPositions") or {}).items()
                     if abs(float(v.get("size", 0) or 0)) > 0}
        out[int(s["subaccountNumber"])] = {
            "equity": float(s.get("equity", 0) or 0),
            "free": float(s.get("freeCollateral", 0) or 0),
            "positions": sorted(positions),
        }
    return out


def plan_even(targets, current):
    """Transfers that even out collateral across `targets`, sourced from the richest.

    Equal split is the sane default for isolation: each subaccount backs one leg of
    the same size, so splitting evenly gives every coin the same buffer. It does not
    create margin — the same equity three ways is the same total.
    """
    total = sum(current.get(t, {}).get("free", 0.0) for t in targets)
    if total <= 0:
        return [], "no free collateral in any mapped subaccount"
    want = total / len(targets)
    moves = []
    donors = sorted(((current.get(t, {}).get("free", 0.0) - want, t)
                     for t in targets), reverse=True)
    needers = [(want - current.get(t, {}).get("free", 0.0), t)
               for t in targets if current.get(t, {}).get("free", 0.0) < want - 0.01]
    for need, dst in sorted(needers, reverse=True):
        remaining = need
        for i, (surplus, src) in enumerate(donors):
            if remaining <= 0.01 or surplus <= 0.01:
                continue
            amount = round(min(surplus, remaining), 2)
            if amount < 0.01:
                continue
            moves.append((src, dst, amount))
            donors[i] = (surplus - amount, src)
            remaining -= amount
    return moves, f"even split at {want:.2f} USDC each"


def _is_sequence_mismatch(err):
    return "account sequence mismatch" in str(err)


def _expected_sequence(err):
    """The sequence the chain says it wants, from its error text. None if absent."""
    m = re.search(r"expected (\d+)", str(err))
    return int(m.group(1)) if m else None


async def send(node, wallet, owner, src, dst, amount, address=None):
    """One subaccount transfer, keeping the local sequence in step with the chain.

    Wallet.from_mnemonic reads the account sequence ONCE. Every broadcast increments
    it on-chain, so a second transfer signed from the same wallet object reuses a
    spent number and is rejected: "account sequence mismatch, expected 14, got 13".
    A multi-transfer run therefore always landed exactly its first transfer and then
    died — which is how --even left the book half-balanced.

    Increment after a successful send, and on a mismatch resync to the number the
    chain asked for and retry once. The retry is safe: a rejected transaction was
    never committed, so this cannot double-send. Only a genuine mismatch is retried;
    anything else propagates.
    """
    def _msg():
        return node.transfer(
            wallet,
            SubaccountId(owner=owner, number=src),
            SubaccountId(owner=owner, number=dst),
            USDC_ASSET_ID,
            int(round(amount * USDC_QUANTUMS)),
        )

    try:
        resp = await _msg()
    except Exception as e:
        if not _is_sequence_mismatch(e):
            raise
        want = _expected_sequence(e)
        if want is None and address is not None:
            account = await node.get_account(address)
            want = account.sequence
        if want is None:
            raise
        print(f"    (sequence was {wallet.sequence}, chain wants {want} — resyncing)")
        wallet.sequence = want
        resp = await _msg()
    wallet.sequence += 1
    return resp


async def main(args):
    cfg = ExecutorConfig()
    network, creds = cfg.venue("dydx")
    address = creds.get("account_address")
    indexer = INDEXER[network]

    # The seed is needed only to SIGN. Reading balances and planning transfers are
    # public-indexer operations, so with no flags this doubles as the subaccount
    # viewer — which matters because the dYdX web app is built around subaccount 0 and
    # will not show you an isolated coin sitting in #1 or #2. Demanding a wallet seed
    # to answer "where is my money" would be a bad trade.
    mnemonic = os.environ.get("DYDX_MAIN_MNEMONIC")
    if mnemonic:
        derived = _address_from_mnemonic(mnemonic)
        if derived != address:
            sys.exit(f"WRONG SEED: it derives {derived}, but config expects"
                     f" {address}. Refusing before signing anything.")
    elif args.broadcast:
        sys.exit(
            "No DYDX_MAIN_MNEMONIC in the environment.\n"
            "  This needs the OWNER key — the bot's trade-only credential cannot\n"
            "  sign a transfer, by design. In the shell you run this from:\n"
            "    $env:DYDX_MAIN_MNEMONIC = 'word word ...'\n"
            "  It disappears when that terminal closes. Do NOT put it in ainara.yaml."
        )

    current = read_subaccounts(indexer, address)
    mapped = {str(k).upper(): int(v)
              for k, v in (cfg.get("trading.dydx.subaccounts", {}) or {}).items()}

    print(f"network        : {network}")
    print(f"account        : {address}")
    print(f"isolation map  : {mapped or '(unset — nothing to fund)'}")
    print("\ncurrent subaccounts:")
    for num in sorted(current):
        s = current[num]
        held = ", ".join(s["positions"]) or "flat"
        print(f"  #{num}: equity {s['equity']:>8.2f}  free {s['free']:>8.2f}  [{held}]")
    for num in sorted(set(mapped.values()) - set(current)):
        print(f"  #{num}: does not exist yet (it will, the moment it is funded)")
    if mapped:
        print("\nrouting:")
        for coin, num in sorted(mapped.items(), key=lambda kv: kv[1]):
            sub = current.get(num)
            where = (f"free {sub['free']:.2f},"
                     f" {', '.join(sub['positions']) or 'flat'}"
                     if sub else "UNFUNDED — this coin cannot open")
            print(f"  {coin:<5} -> #{num}  ({where})")
    if not mnemonic:
        print("\n(read-only: no DYDX_MAIN_MNEMONIC set, so nothing can be sent)")

    if args.even:
        targets = sorted(set(mapped.values()) | {0})
        moves, why = plan_even(targets, current)
        print(f"\nplan: {why}")
    elif args.to is not None and args.amount is not None:
        moves, _ = [(args.source, args.to, float(args.amount))], "explicit"
    else:
        print("\nNothing to do. Pass --even, or --to N --amount X.")
        return

    if not moves:
        print("  (already balanced — no transfers needed)")
        return

    # Refuse anything that would thin an open position's margin, or strip a source.
    for src, dst, amount in moves:
        s = current.get(src, {"free": 0.0, "positions": []})
        if s["positions"]:
            sys.exit(f"REFUSING: subaccount #{src} holds {', '.join(s['positions'])}."
                     " Moving its collateral out thins that position's margin and"
                     " pushes its liquidation price closer. Close it first.")
        if amount > s["free"] + 1e-9:
            sys.exit(f"REFUSING: #{src} has {s['free']:.2f} free, cannot send"
                     f" {amount:.2f}.")
        if s["free"] - amount < args.min_source:
            sys.exit(f"REFUSING: sending {amount:.2f} would leave #{src} with"
                     f" {s['free'] - amount:.2f}, below --min-source"
                     f" {args.min_source:.2f}.")

    print("\ntransfers:")
    for src, dst, amount in moves:
        print(f"  #{src} -> #{dst}   {amount:.2f} USDC")

    if not args.broadcast:
        print("\nDRY RUN — nothing sent. Re-run with --broadcast to move funds.")
        return

    node = await NodeClient.connect(dydx_network(network, creds.get("node_url")).node)
    wallet = await Wallet.from_mnemonic(node, mnemonic, address)
    print("\nBROADCASTING (signed by the owner key)...")
    # Report per transfer and stop at the first real failure, but never let a
    # traceback be the summary: a half-applied run is exactly when you need to read
    # what landed. Re-running is safe — the plan is recomputed from live balances,
    # so completed transfers are simply not planned again.
    sent, failed = [], None
    for src, dst, amount in moves:
        try:
            resp = await send(node, wallet, address, src, dst, amount,
                              address=address)
        except Exception as e:
            failed = (src, dst, amount, f"{type(e).__name__}: {e}")
            break
        code = getattr(getattr(resp, "tx_response", resp), "code", resp)
        ok = code == 0
        print(f"  #{src} -> #{dst} {amount:.2f}: tx code {code}"
              f"{'  OK' if ok else '  FAILED'}")
        if not ok:
            failed = (src, dst, amount, f"tx code {code}")
            break
        sent.append((src, dst, amount))

    print(f"\n{len(sent)} of {len(moves)} transfer(s) landed.")
    if failed:
        src, dst, amount, why = failed
        print(f"  STOPPED on #{src} -> #{dst} {amount:.2f}: {why}")
        print("  Nothing was lost — a rejected transfer is not committed. Re-run the"
              " same command; the plan is rebuilt from live balances.")
    print("\nRe-read balances in a few seconds (the indexer lags the chain):")
    print(f"  {sys.argv[0]}  (no flags)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--even", action="store_true",
                   help="even the collateral across every mapped subaccount")
    p.add_argument("--to", type=int, help="destination subaccount number")
    p.add_argument("--amount", type=float, help="USDC to send")
    p.add_argument("--source", type=int, default=0,
                   help="source subaccount (default 0)")
    p.add_argument("--min-source", type=float, default=5.0,
                   help="refuse if the source would drop below this (default 5)")
    p.add_argument("--broadcast", action="store_true",
                   help="actually send; without it this is a dry run")
    asyncio.run(main(p.parse_args()))
