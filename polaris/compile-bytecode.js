const bytenode = require('bytenode');
const path = require('path');
async function compile() {
  const filePath = path.join(__dirname, 'main.protected.js');
  const destPath = path.join(__dirname, 'main.protected.jsc');
  try {
    await bytenode.compileFile({
        filename: filePath,
        output: destPath,
        electronMain: true
    });
    console.log('✅ Bytecode generado con éxito: main.protected.jsc');
  } catch (err) {
    console.error('❌ Error al compilar bytecode:', err);
    process.exit(1);
  }
}
compile();
