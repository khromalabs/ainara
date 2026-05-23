<!DOCTYPE html>
<html>
<head>
    <title>Ainara Authentication</title>
    <link rel="icon" href="/assets/icon.png" />
    <style>
        body { font-family: 'Segoe UI', sans-serif; background: #1e1e1e; color: #fff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }
        .card { background: #2d2d2d; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5); text-align: center; max-width: 400px; width: 100%; }
        h2 { margin-top: 0; color: #4caf50; }
        button { background: #512da8; color: white; border: none; padding: 12px 24px; border-radius: 6px; font-size: 16px; cursor: pointer; transition: background 0.3s; width: 100%; margin-top: 1rem; }
        button:hover { background: #673ab7; }
        button:disabled { background: #555; cursor: not-allowed; }
        .status { margin-top: 1rem; font-size: 0.9rem; color: #aaa; }
        .error { color: #ff5252; }
        .security-note { background: #252525; padding: 10px; border-radius: 6px; margin: 1rem 0; font-size: 0.85rem; color: #aaa; display: flex; align-items: center; justify-content: center; gap: 8px; border: 1px solid #333; }
        .lock-icon { width: 14px; height: 14px; fill: #4caf50; }
    </style>
    <script src="/assets/js/solana-web3.min.js"></script>
</head>
<body>
    <div class="card">
        <h2>Ainara Login</h2>
        <p>Connect your Solana wallet to verify ownership of $AINARA tokens.</p>
        <div class="security-note">
            <svg class="lock-icon" viewBox="0 0 24 24"><path d="M18 8h-1V6c0-2.76-2.24-5-5-5S7 3.24 7 6v2H6c-1.1 0-2 .9-2 2v10c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V10c0-1.1-.9-2-2-2zm-9-2c0-1.66 1.34-3 3-3s3 1.34 3 3v2H9V6zm9 14H6V10h12v10zm-6-3c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2z"/></svg>
            <span>Read-Only Access. This permission does not allow any type of transfer.</span>
        </div>
        <button id="connectBtn" onclick="connectAndSign()">Connect Wallet</button>
        <div id="status" class="status"></div>
    </div>

    <script>
        const MESSAGE = "{{auth_message}}";

        async function connectAndSign() {
            const status = document.getElementById('status');
            const btn = document.getElementById('connectBtn');

            if (!window.solana || !window.solana.isPhantom) {
                status.innerHTML = "Phantom wallet not found. Please install it.";
                status.className = "status error";
                return;
            }

            try {
                btn.disabled = true;
                status.innerText = "Connecting...";

                // Connect
                const resp = await window.solana.connect();
                const publicKey = resp.publicKey.toString();

                status.innerText = "Please sign the message in your wallet...";

                // Sign
                const encodedMessage = new TextEncoder().encode(MESSAGE);
                const signedMessage = await window.solana.signMessage(encodedMessage, "utf8");

                status.innerText = "Verifying...";

                // Send to Backend
                const response = await fetch('/auth/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        wallet: publicKey,
                        signature: Array.from(signedMessage.signature),
                        message: MESSAGE
                    })
                });

                const result = await response.json();

                if (result.success) {
                    status.innerHTML = "<span style='color:#4caf50'>Success! You can close this window.</span>";
                    btn.style.display = 'none';
                } else {
                    throw new Error(result.message);
                }

            } catch (err) {
                console.error(err);
                status.innerText = "Error: " + err.message;
                status.className = "status error";
                btn.disabled = false;
            }
        }
    </script>
</body>
</html>
