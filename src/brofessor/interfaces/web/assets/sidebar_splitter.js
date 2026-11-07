// Only presentation state lives here. Dragging never sends a Streamlit event.
export default function ({parentElement, data}) {
    const bar = parentElement.querySelector(".brofessor-sidebar-divider");
    const panels = parentElement.closest(".st-key-sidebar-panels");
    if (!bar || !panels) return;
    const storageKey = data.storage_key;
    let share = 50;
    try {
        const saved = Number(localStorage.getItem(storageKey));
        if (saved >= 15 && saved <= 85) share = saved;
    } catch { /* Resizing also works when browser storage is disabled. */ }
    bar.setAttribute("aria-label", data.label);
    bar.setAttribute("title", data.label);
    bar.setAttribute("aria-valuemin", "15");
    bar.setAttribute("aria-valuemax", "85");
    function apply(value, persist = false) {
        share = Math.max(15, Math.min(85, value));
        panels.style.setProperty("--brofessor-project-share", share + "%");
        bar.setAttribute("aria-valuenow", Math.round(share));
        if (persist) {
            try { localStorage.setItem(storageKey, String(share)); } catch {}
        }
    }
    function move(event) {
        if (!bar.hasPointerCapture(event.pointerId)) return;
        const bounds = panels.getBoundingClientRect();
        apply((event.clientY - bounds.top) / bounds.height * 100);
    }
    function start(event) {
        if (event.button !== 0) return;
        event.preventDefault();
        bar.setPointerCapture(event.pointerId);
        bar.focus();
    }
    function stop(event) {
        if (bar.hasPointerCapture(event.pointerId)) {
            bar.releasePointerCapture(event.pointerId);
            apply(share, true);
        }
    }
    function keyboard(event) {
        const values = {ArrowUp: share - 5, ArrowDown: share + 5, Home: 15, End: 85};
        if (!(event.key in values)) return;
        event.preventDefault();
        apply(values[event.key], true);
    }
    apply(share);
    const pointerDownEvent = "pointerdown";
    const pointerMoveEvent = "pointermove";
    const pointerUpEvent = "pointerup";
    const pointerCancelEvent = "pointercancel";
    const keyDownEvent = "keydown";
    bar.addEventListener(pointerDownEvent, start);
    bar.addEventListener(pointerMoveEvent, move);
    bar.addEventListener(pointerUpEvent, stop);
    bar.addEventListener(pointerCancelEvent, stop);
    bar.addEventListener(keyDownEvent, keyboard);
    return () => {
        bar.removeEventListener(pointerDownEvent, start);
        bar.removeEventListener(pointerMoveEvent, move);
        bar.removeEventListener(pointerUpEvent, stop);
        bar.removeEventListener(pointerCancelEvent, stop);
        bar.removeEventListener(keyDownEvent, keyboard);
    };
}
