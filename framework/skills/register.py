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


import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def register_core_skills(capabilities_manager) -> Dict[str, Any]:
    """
    Register all core skills with the capabilities manager
    
    Args:
        capabilities_manager: The CapabilitiesManager instance
        
    Returns:
        Dictionary of registered core skills
    """
    logger.info("Registering core skills")
    
    core_skills = {}
    
    # Document Search skill
    try:
        from .document_search import DocumentSearchSkill
        document_search = DocumentSearchSkill()
        capabilities_manager.register_skill(document_search)
        core_skills["document_search"] = document_search
        logger.info("Registered DocumentSearch core skill")
    except Exception as e:
        logger.error(f"Failed to register DocumentSearch core skill: {e}", exc_info=True)
    
    # Add more core skills here as they are developed
    
    return core_skills