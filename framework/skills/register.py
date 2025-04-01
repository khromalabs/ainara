# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez - khromalabs.org

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
