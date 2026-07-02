import type * as Monaco from 'monaco-editor';

export const hclTokensProvider: Monaco.languages.IMonarchLanguage = {
  tokenizer: {
    root: [
      [/#.*$/, 'comment'],
      [/\/\/.*$/, 'comment'],
      [/\/\*/, 'comment', '@comment'],
      [/"([^"\\]|\\.)*$/, 'string.invalid'],
      [/"/, 'string', '@string'],
      [/\d*\.\d+([eE][-+]?\d+)?/, 'number.float'],
      [/\d+/, 'number'],
      [/\b(resource|data|variable|output|locals|module|provider|terraform)\b/, 'keyword'],
      [/\b(true|false|null)\b/, 'keyword.literal'],
      [/[a-z_$][\w$]*/, 'identifier'],
      [/[A-Z][\w$]*/, 'type.identifier'],
      [/[{}()[\]]/, '@brackets'],
      [/[<>](?!@symbols)/, '@brackets'],
      [/@symbols/, 'operator'],
      { include: '@whitespace' },
    ],
    comment: [
      [/[^/*]+/, 'comment'],
      [/\/\*/, 'comment', '@push'],
      ['\\*/', 'comment', '@pop'],
      [/[/*]/, 'comment'],
    ],
    string: [
      [/[^\\"]+/, 'string'],
      [/\\./, 'string.escape.invalid'],
      [/"/, 'string', '@pop'],
    ],
    whitespace: [
      [/[ \t\r\n]+/, 'white'],
      [/\/\*/, 'comment', '@comment'],
      [/\/\/.*$/, 'comment'],
    ],
  },
  symbols: /[=><!~?:&|+\-*/^%]+/,
};

export function registerHclLanguage(monaco: typeof Monaco): void {
  if (!monaco.languages.getLanguages().find((lang: Monaco.languages.ILanguageExtensionPoint) => lang.id === 'hcl')) {
    monaco.languages.register({ id: 'hcl' });
    monaco.languages.setMonarchTokensProvider('hcl', hclTokensProvider);
  }
}
