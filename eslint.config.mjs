import globals from "globals";
import pluginJs from "@eslint/js";

/** @type {import('eslint').Linter.Config[]} */
export default [
    {
        files: ["**/*.js"],
        languageOptions: {
            sourceType: "commonjs",
            globals: {
                ...globals.browser,
                ...globals.node,
                // Electron specific globals
                electron: "readonly",
                process: "readonly",
                __dirname: "readonly",
                __filename: "readonly",
                node: true,
                browser: true,
                es2022: true,
                commonjs: true
            },
        },
    },
    pluginJs.configs.recommended,
];
