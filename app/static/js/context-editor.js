document.addEventListener('alpine:init', () => {
    Alpine.data('contextEditor', () => {
        let editorInstance = null;

        return {
            initEditor() {
                const rawContextInput = document.getElementById('hidden-raw-context');
                if (!rawContextInput) return;

                let editorData = { time: Date.now(), blocks: [], version: "2.29.0" };
                try {
                    const rawVal = rawContextInput.value.trim();
                    if (rawVal.startsWith('{')) {
                        editorData = JSON.parse(rawVal);
                    } else if (rawVal.length > 0) {
                        // Fallback: Convert raw markdown/text to paragraph blocks
                        const paragraphs = rawVal.split('\n\n').filter(p => p.trim().length > 0);
                        editorData.blocks = paragraphs.map(p => ({
                            type: "paragraph",
                            data: { text: p.trim().replace(/\n/g, '<br>') }
                        }));
                    }
                } catch (e) {
                    console.error("Failed to parse Editor.js JSON data:", e);
                }

                editorInstance = new EditorJS({
                    holder: 'editorjs-container',
                    logLevel: 'ERROR',
                    data: editorData,
                    onReady: () => {
                        new Undo({ editor: editorInstance });
                    },
                    tools: {
                        header: {
                            class: Header,
                            config: {
                                levels: [1, 2, 3, 4, 5, 6],
                                defaultLevel: 3
                            }
                        },
                        list: List,
                        code: CodeTool,
                        delimiter: Delimiter
                    }
                });
            },

            saveEditor() {
                if (!editorInstance) return;
                
                editorInstance.save().then((outputData) => {
                    document.getElementById('hidden-raw-context').value = JSON.stringify(outputData);
                    
                    // Trigger HTMX natively on the form
                    const form = document.getElementById('context-form');
                    if (form) {
                        htmx.trigger(form, 'submit');
                    }
                }).catch((error) => {
                    console.error('EditorJS saving failed: ', error);
                });
            }
        };
    });
});
