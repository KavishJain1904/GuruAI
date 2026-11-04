/** Recorded quiz answers and self-ratings; loaded when the history panel opens. */
(function () {
    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, ch => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[ch]));
    }

    function renderEvent(event) {
        const result = event.kind === "self_rating"
            ? `Self-rating · ${Math.round(event.score * 10)}/10`
            : `Quiz answer · ${event.score === 1 ? "Correct" : "Incorrect"}`;
        const before = Math.round(event.mastery_before * 100);
        const after = Math.round(event.mastery_after * 100);
        const nextReview = String(event.next_review_date).slice(0, 10);
        const date = String(event.reviewed_at).replace("T", " ").slice(0, 16);
        return `<article class="py-4 border-t border-outline-variant/10 text-sm">
            <p class="font-semibold text-on-surface">${escapeHtml(event.subject)} · ${escapeHtml(event.topic)}</p>
            <p class="text-primary text-xs mt-1">${escapeHtml(result)} · ${escapeHtml(date)}</p>
            <p class="text-on-surface-variant text-xs mt-1">Mastery: ${before}% → ${after}% · Next review: ${escapeHtml(nextReview)}</p>
            ${event.question ? `<p class="mt-2 text-on-surface">${escapeHtml(event.question)}</p>` : ""}
            ${event.selected_answer != null ? `<p class="text-on-surface-variant">Your answer: ${escapeHtml(event.selected_answer)}</p>` : ""}
            ${event.correct_answer != null ? `<p class="text-on-surface-variant">Correct answer: ${escapeHtml(event.correct_answer)}</p>` : ""}
            ${event.notes ? `<p class="text-on-surface-variant mt-2 whitespace-pre-wrap">${escapeHtml(event.notes)}</p>` : ""}
        </article>`;
    }

    window.initReviewHistoryWidget = function (containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.innerHTML = `<details class="bg-surface-container rounded-2xl border border-outline-variant/10 p-5">
            <summary class="cursor-pointer font-semibold text-on-surface">Review history</summary>
            <p class="text-xs text-on-surface-variant mt-2">Quiz answers and self-ratings recorded from now on. Earlier reviews are not available.</p>
            <div data-history-list aria-live="polite"></div>
            <div class="flex gap-4 mt-3">
                <button type="button" data-history-previous class="text-primary text-sm" hidden>Previous</button>
                <button type="button" data-history-next class="text-primary text-sm" hidden>Next</button>
                <button type="button" data-history-refresh class="text-primary text-sm">Refresh</button>
            </div>
        </details>`;
        const details = container.querySelector("details");
        const list = container.querySelector("[data-history-list]");
        const previous = container.querySelector("[data-history-previous]");
        const next = container.querySelector("[data-history-next]");
        let offset = 0;
        let requestId = 0;
        async function load() {
            const id = ++requestId;
            previous.hidden = true;
            next.hidden = true;
            list.textContent = "Loading review history…";
            try {
                const response = await fetch(`/api/reviews?limit=10&offset=${offset}`);
                if (!response.ok) throw new Error("Unable to load review history. Try Refresh.");
                const data = await response.json();
                if (id !== requestId) return;
                list.innerHTML = data.items.length ? data.items.map(renderEvent).join("")
                    : '<p class="text-sm text-on-surface-variant py-4">No reviews recorded yet.</p>';
                previous.hidden = offset === 0;
                next.hidden = !data.has_more;
            } catch (error) {
                if (id === requestId) list.textContent = error.message;
            }
        }
        details.addEventListener("toggle", () => { if (details.open) load(); });
        previous.addEventListener("click", () => { offset = Math.max(0, offset - 10); load(); });
        next.addEventListener("click", () => { offset += 10; load(); });
        container.querySelector("[data-history-refresh]").addEventListener("click", () => { offset = 0; load(); });
        window.addEventListener("review-recorded", () => {
            offset = 0;
            if (details.open) load();
        });
    };
})();
