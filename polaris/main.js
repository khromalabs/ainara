const path = require('path');

// Check if we should use source files directly (development mode)
if (process.env.AINARA_USE_SOURCE === '1') {
  // Load the source file directly for development
  require(path.join(__dirname, 'main.protected.js'));
} else {
  // Load the compiled bytecode for production
  const bytenode = require('bytenode');
  require(path.join(__dirname, 'main.protected.jsc'));
}
