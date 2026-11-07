// Native disclosures retain their keyboard behavior. Expose their titles in
// heading navigation too, without adding a second visible title or UI state.
export default function ({parentElement}) {
    const root = parentElement.ownerDocument;
    function headings() {
        for (const label of root.querySelectorAll(
            '[class*="st-key-major-"] > [data-testid="stExpander"] > details > summary [data-testid="stMarkdownContainer"] p'
        )) {
            label.setAttribute("role", "heading");
            label.setAttribute("aria-level", "3");
        }
    }
    headings();
    const observer = new MutationObserver(headings);
    observer.observe(root.body, {childList: true, subtree: true});
    return () => observer.disconnect();
}
