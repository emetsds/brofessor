// Streamlit's native uploader has no label option for its choose button.
// Localize presentation only; the native file input and upload protocol stay intact.
export default function ({parentElement, data}) {
    const dialog = parentElement.closest('[role="dialog"]');
    if (!dialog) return;
    function translate() {
        const uploader = dialog.querySelector('[data-testid="stFileUploader"]');
        if (!uploader) return;
        for (const button of uploader.querySelectorAll('button')) {
            const label = button.querySelector('[data-testid="stMarkdownContainer"] p');
            if (label && ['Upload', 'Browse files', 'Add files'].includes(label.textContent)) label.textContent = data.choose;
            if (['Upload', 'Browse files', 'Add files'].includes(button.textContent.trim())) button.textContent = data.choose;
        }
        const input = uploader.querySelector('input[type="file"]');
        if (input) input.setAttribute('aria-label', data.choose);
        const instructions = uploader.querySelector('[data-testid="stFileUploaderDropzoneInstructions"] span');
        if (instructions && instructions.textContent !== data.limit) instructions.textContent = data.limit;
    }
    translate();
    const observer = new MutationObserver(translate);
    observer.observe(dialog, {childList: true, subtree: true});
    return () => observer.disconnect();
}
