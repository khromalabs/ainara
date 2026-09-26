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

import os
import logging
import requests
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from ainara.framework.config import config

logger = logging.getLogger(__name__)

text_path = config.get(
    "memory.text_storage.scheduler_jobs_path",
    os.path.join(config.get("data.directory"), "orakle_apscheduler.db"),
)
jobstores = {
    'default': SQLAlchemyJobStore(url=f'sqlite:///{text_path}')
}
_scheduler_instance = None


def _run_job_proxy(skill_name, kwargs):
    if _scheduler_instance:
        _scheduler_instance._execute_job(skill_name, kwargs)
    else:
        logger.error(f"Scheduler instance missing for job: {skill_name}")


class OrakleScheduler:
    def __init__(self, capabilities_manager, config):
        global _scheduler_instance
        _scheduler_instance = self
        self.cap_manager = capabilities_manager
        self.config = config
        self.scheduler = BackgroundScheduler(jobstores=jobstores)
        # Default to localhost pybridge if not configured
        self.pybridge_url = config.get(
            "scheduler.pybridge_url", "http://127.0.0.1:8101"
        )
        self.enabled = config.get("scheduler.enabled", True)

    def start(self):
        if not self.enabled:
            logger.info("Scheduler is disabled in configuration.")
            return

        logger.info("Starting Orakle Scheduler...")
        self._discover_and_schedule_jobs()

        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Orakle Scheduler started.")

    def _discover_and_schedule_jobs(self):
        """Scans loaded capabilities for default_schedule and registers them."""
        capabilities = self.cap_manager.get_capabilities()

        for name, info in capabilities.items():
            # We only support scheduling for native skills for now,
            # as we need access to the class attribute 'default_schedule'
            if info.get("type") != "skill":
                logger.info(f"skipping skill {name}: is not basic type skill")
                continue

            instance = self.cap_manager.get_capability(name)
            if not instance:
                logger.info(f"skipping skill {name}: not instanced in manager")
                continue

            # Check if the skill has a default schedule
            schedule_config = getattr(instance, "default_schedule", None)

            # Check if there is an override in the main config
            # config structure: scheduler.overrides.<SkillName>
            override = self.config.get(f"scheduler.overrides.{name}")

            # Use override if present, otherwise default.
            # If override is explicitly False/None, it disables the schedule.
            final_config = override if override is not None else schedule_config

            if final_config:
                # Ensure we work with a copy to avoid modifying the class attribute
                job_config = final_config.copy()
                self._add_job_from_config(name, job_config)
                logger.info(f"added skill {name} job from config")

    def _add_job_from_config(self, skill_name, job_config):
        try:
            # Extract execution arguments for the skill
            skill_kwargs = job_config.pop("kwargs", {})

            # Extract trigger type, "cron" by default
            trigger_type = job_config.pop("trigger", "cron")

            # Extract "default" config
            job_config.pop("default")

            # Prepare explicit options for add_job
            add_job_options = {
                "trigger": trigger_type,
                "args": [skill_name, skill_kwargs],
                "id": f"job_{skill_name}",
                "replace_existing": True,
                "coalesce": False
            }

            # Handle misfire_grace_time explicitly if present.
            # If not present, we let APScheduler use its default (usually 1s/strict).
            if "misfire_grace_time" in job_config:
                # add_job_options["misfire_grace_time"] = job_config.pop(
                #     "misfire_grace_time"
                # )
                # If grace time, coalesce is True by default
                if "coalesce" not in job_config:
                    add_job_options["coalesce"] = True

            # Handle coalesce explicitly if present
            # if "coalesce" in job_config:
            #     add_job_options["coalesce"] = job_config.pop("coalesce")

            # The rest of the config are arguments for the trigger
            # (e.g., hour='*', minute='30')

            logger.info(
                f"Scheduling skill '{skill_name}' with options {add_job_options}"
                f" and trigger args {job_config}"
            )

            self.scheduler.add_job(
                _run_job_proxy,
                **add_job_options,
                **job_config,  # Remaining args are trigger args
            )
        except Exception as e:
            logger.error(
                f"Failed to schedule job for skill '{skill_name}': {e}"
            )

    def _execute_job(self, skill_name, kwargs):
        """The function executed by the scheduler."""
        logger.info(f"Executing scheduled skill: {skill_name}")
        try:
            # 1. Execute the skill
            result = self.cap_manager.execute_capability(skill_name, kwargs)

            # 2. Send result to Pybridge
            self._send_result_to_pybridge(skill_name, result)

        except Exception as e:
            logger.error(
                f"Error executing scheduled skill '{skill_name}': {e}",
                exc_info=True,
            )

    def _send_result_to_pybridge(self, skill_name, result):
        endpoint = f"{self.pybridge_url}/framework/queue/push"
        payload = {
            "source": skill_name,
            "type": "scheduled_execution",
            "timestamp": datetime.utcnow().isoformat(),
            "result": result,
        }

        try:
            response = requests.post(endpoint, json=payload, timeout=5)
            if response.status_code == 200:
                logger.info(
                    f"Successfully pushed result for '{skill_name}' to"
                    " Pybridge."
                )
            else:
                logger.warning(
                    "Failed to push result to Pybridge. Status:"
                    f" {response.status_code}"
                )
        except Exception as e:
            logger.error(f"Connection error pushing result to Pybridge: {e}")

    def shutdown(self):
        if self.scheduler.running:
            logger.info("Shutting down Orakle Scheduler...")
            self.scheduler.shutdown()
