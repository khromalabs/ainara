# Ainara - Open Source AI Assistant Framework
# Copyright (C) 2025 Rubén Gómez http://www.khromalabs.org

# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, see
# <https://www.gnu.org/licenses/>

import os
import pystache
from datetime import datetime
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

class TemplateManager:
    """Template manager using Mustache templating system with .mu extension"""
    
    def __init__(self, template_dir: Optional[str] = None, extension: str = "mu"):
        """Initialize the template manager
        
        Args:
            template_dir: Directory containing template files. If None, 
                          uses 'templates' subdirectory of current file.
            extension: File extension for template files (without the dot)
        """
        if template_dir is None:
            self.template_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), 
                'templates'
            )
        else:
            self.template_dir = template_dir
            
        self.extension = extension
        self.template_cache = {}
        
        # Ensure template directory exists
        os.makedirs(self.template_dir, exist_ok=True)
        
        self.renderer = pystache.Renderer(
            search_dirs=[self.template_dir],
            file_extension=self.extension
        )
        
        logger.info(f"Template manager initialized with directory: {self.template_dir}")
        
    def list_templates(self):
        """List all available templates"""
        templates = []
        for file in os.listdir(self.template_dir):
            if file.endswith(f".{self.extension}"):
                templates.append(file[:-len(self.extension)-1])  # Remove extension
        return sorted(templates)
        
    def render(self, template_name: str, context: Dict[str, Any] = None) -> str:
        """Render a template with the given context
        
        Args:
            template_name: Name of the template file (without extension)
                          Can use dot notation (e.g., "framework.chat_manager.system_prompt")
            context: Dictionary of variables to substitute in the template
            
        Returns:
            The rendered template as a string
        """
        if context is None:
            context = {}
            
        # Add some default variables
        full_context = {
            'current_date': datetime.now().strftime('%Y-%m-%d'),
            'current_time': datetime.now().strftime('%H:%M:%S'),
        }
        full_context.update(context)
        
        try:
            # Use pystache to render the template
            return self.renderer.render_name(template_name, full_context)
        except Exception as e:
            logger.error(f"Error rendering template '{template_name}': {e}")
            # Return a fallback message in case of error
            return f"[Error rendering template: {template_name}]"
