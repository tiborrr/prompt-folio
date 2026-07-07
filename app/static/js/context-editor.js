document.addEventListener('alpine:init', () => {
    Alpine.data('contextEditor', () => ({
        editor: null,

        initEditor() {
            const rawContextInput = document.getElementById('hidden-raw-context');
            if (!rawContextInput) return;

            this.editor = new EditorJS({
                holder: 'editorjs-container',
                data: this.markdownToEditorJs(rawContextInput.value),
                tools: {
                    header: Header,
                    list: List
                }
            });
        },

        saveEditor() {
            if (!this.editor) return;
            
            this.editor.save().then((outputData) => {
                const md = this.editorJsToMarkdown(outputData);
                document.getElementById('hidden-raw-context').value = md;
                
                // Trigger HTMX natively on the form
                const form = document.getElementById('context-form');
                if (form) {
                    htmx.trigger(form, 'submit');
                }
            }).catch((error) => {
                console.error('EditorJS saving failed: ', error);
            });
        },

        markdownToEditorJs(md) {
            const blocks = [];
            const paragraphs = md.split('\n\n');
            paragraphs.forEach(p => {
                if (p.startsWith('### ')) {
                    blocks.push({ type: 'header', data: { text: p.replace('### ', ''), level: 3 } });
                } else if (p.startsWith('## ')) {
                    blocks.push({ type: 'header', data: { text: p.replace('## ', ''), level: 2 } });
                } else if (p.startsWith('# ')) {
                    blocks.push({ type: 'header', data: { text: p.replace('# ', ''), level: 1 } });
                } else if (p.startsWith('- ')) {
                    const items = p.split('\n').filter(item => item.startsWith('- ')).map(item => item.replace('- ', ''));
                    if (items.length > 0) {
                        blocks.push({ type: 'list', data: { style: 'unordered', items: items } });
                    }
                } else if (p.trim() !== '') {
                    const htmlText = p.replace(/\n/g, '<br>');
                    blocks.push({ type: 'paragraph', data: { text: htmlText } });
                }
            });
            return { blocks: blocks };
        },

        editorJsToMarkdown(data) {
            let md = '';
            data.blocks.forEach(block => {
                if (block.type === 'header') {
                    md += '#'.repeat(block.data.level) + ' ' + block.data.text + '\n\n';
                } else if (block.type === 'paragraph') {
                    const plainText = block.data.text.replace(/<br>/gi, '\n');
                    md += plainText + '\n\n';
                } else if (block.type === 'list') {
                    block.data.items.forEach(item => {
                        md += '- ' + item + '\n';
                    });
                    md += '\n';
                }
            });
            return md.trim();
        }
    }));
});
