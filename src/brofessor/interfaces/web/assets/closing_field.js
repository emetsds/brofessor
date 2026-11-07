// Streamlit applies text on blur. Preserve an active field when its page closes first.
export default function ({data, setTriggerValue}) {
    const prefix = data.storage_prefix + data.key + ":";
    const pageHideEvent = "pagehide";
    for (const id of data.received) localStorage.removeItem(prefix + id);
    const pending = Object.keys(localStorage).find(key => key.startsWith(prefix));
    if (pending) {
        setTriggerValue(data.trigger_name, JSON.parse(localStorage.getItem(pending)));
    }
    function onClose() {
        const input = document.activeElement;
        if (!input || !("value" in input)) return;
        for (const [key, field] of Object.entries(data.fields)) {
            const cls = "st-key-" + key.trim().replace(/[^a-zA-Z0-9_-]/g, "-");
            if (!input.closest("." + cls) || input.value === field.value) continue;
            const id = crypto.randomUUID();
            localStorage.setItem(prefix + id, JSON.stringify({
                id, revision: data.revision, content: data.content,
                path: field.path, lines: field.lines, text: input.value
            }));
            break;
        }
    }
    window.addEventListener(pageHideEvent, onClose);
    return () => window.removeEventListener(pageHideEvent, onClose);
}
