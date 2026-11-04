/**
 * study-tracker.js — Modal for recording a study-session score (SRS feature).
 *
 * Include with:  <script src="/widgets/study-tracker.js"></script>
 * Use with:      const result = await showStudyTracker(topicId, topicName);
 *
 * Resolves with the API response on save, or `null` if the user skips/dismisses.
 * Backend contract: POST /api/topics/{topicId}/mark-reviewed  { score, notes }
 */
(function () {
    const API = "";
    let stylesInjected = false;

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function injectStylesOnce() {
        if (stylesInjected) return;
        stylesInjected = true;
        const style = document.createElement("style");
        style.id = "study-tracker-styles";
        style.textContent = `
            @keyframes study-tracker-confetti-fall {
                0%   { transform: translateY(-12px) rotate(0deg);   opacity: 1; }
                100% { transform: translateY(160px) rotate(360deg); opacity: 0; }
            }
            .study-tracker-confetti-piece {
                position: absolute;
                top: 0;
                width: 6px;
                height: 6px;
                border-radius: 2px;
                animation: study-tracker-confetti-fall 900ms ease-in forwards;
                pointer-events: none;
            }
        `;
        document.head.appendChild(style);
    }

    function launchConfetti(modalEl) {
        const colors = ["#c782ff", "#00e3fd", "#24f07e", "#ffb2b9", "#ffd166"];
        modalEl.style.position = "relative";
        modalEl.style.overflow = "hidden";
        for (let i = 0; i < 24; i++) {
            const piece = document.createElement("span");
            piece.className = "study-tracker-confetti-piece";
            piece.style.left = `${Math.random() * 100}%`;
            piece.style.background = colors[i % colors.length];
            piece.style.animationDelay = `${Math.random() * 150}ms`;
            modalEl.appendChild(piece);
            setTimeout(() => piece.remove(), 1200);
        }
    }

    /** Days between today and an ISO "YYYY-MM-DD" date string. */
    function daysUntil(dateStr) {
        if (!dateStr) return 0;
        const target = new Date(`${dateStr}T00:00:00`);
        const today = new Date();
        today.setHours(0, 0, 0, 0);
        return Math.round((target - today) / 86400000);
    }

    // Only one modal instance should ever be live; calling showStudyTracker again
    // dismisses whatever is currently open (resolving its promise with null).
    let dismissActiveModal = null;

    /**
     * Show the study-tracker modal for a topic. Returns a Promise that resolves
     * with the mark-reviewed API response on save, or null if skipped/dismissed.
     */
    function showStudyTracker(topicId, topicName) {
        if (typeof dismissActiveModal === "function") {
            dismissActiveModal();
        }

        return new Promise((resolve) => {
            injectStylesOnce();

            const backdrop = document.createElement("div");
            backdrop.id = "study-tracker-backdrop";
            backdrop.className =
                "fixed inset-0 z-[200] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 " +
                "opacity-0 transition-opacity duration-200";
            backdrop.innerHTML = `
                <div id="study-tracker-modal"
                    class="bg-surface-container-high rounded-2xl border border-outline-variant/10 w-full max-w-md p-6 shadow-2xl
                           scale-95 opacity-0 transition-all duration-200">
                    <h3 class="text-on-surface font-semibold text-lg mb-1 truncate">${escapeHtml(topicName)}</h3>
                    <p class="text-on-surface-variant text-sm mb-4">How well did you understand?</p>
                    <p class="text-xs text-on-surface-variant mb-4">This self-rating updates your mastery and review date. It does not count as a quiz answer.</p>

                    <div class="mb-2 flex items-center justify-between">
                        <span class="text-xs text-on-surface-variant">Not at all</span>
                        <span id="study-score-display" class="text-2xl font-bold text-primary">5</span>
                        <span class="text-xs text-on-surface-variant">Perfectly</span>
                    </div>
                    <input id="study-score-slider" type="range" min="0" max="10" step="1" value="5"
                        class="w-full accent-primary h-2 rounded-full mb-4" />

                    <textarea id="study-notes" rows="2" inputmode="text" placeholder="Notes (optional)"
                        class="w-full bg-surface-container-lowest border border-outline-variant/20 rounded-xl px-3 py-2 text-sm
                               text-on-surface placeholder:text-on-surface-variant/40 focus:outline-none focus:ring-1
                               focus:ring-primary/40 mb-4 resize-none"></textarea>

                    <div id="study-tracker-feedback" class="hidden mb-4 text-sm rounded-xl px-3 py-2"></div>

                    <div class="flex gap-3">
                        <button id="study-skip-btn"
                            class="flex-1 py-2.5 rounded-full border border-outline-variant/20 text-on-surface-variant text-sm
                                   hover:bg-surface-container-highest transition-colors">
                            Skip
                        </button>
                        <button id="study-save-btn"
                            class="flex-1 py-2.5 rounded-full bg-primary text-on-primary text-sm font-medium
                                   hover:opacity-90 transition-opacity disabled:opacity-60">
                            Save &amp; Continue
                        </button>
                    </div>
                </div>
            `;
            // Mount into #study-tracker-modal-container if the host page defines one,
            // otherwise fall back to <body> (position:fixed makes the parent irrelevant visually).
            const mountPoint = document.getElementById("study-tracker-modal-container") || document.body;
            mountPoint.appendChild(backdrop);

            // Animate in on the next frame so the transition classes actually apply.
            const raf = window.requestAnimationFrame || ((cb) => setTimeout(cb, 16));
            raf(() => {
                backdrop.classList.remove("opacity-0");
                backdrop.querySelector("#study-tracker-modal").classList.remove("scale-95", "opacity-0");
            });

            const modal = backdrop.querySelector("#study-tracker-modal");
            const slider = backdrop.querySelector("#study-score-slider");
            const scoreDisplay = backdrop.querySelector("#study-score-display");
            const notesEl = backdrop.querySelector("#study-notes");
            const feedbackEl = backdrop.querySelector("#study-tracker-feedback");
            const saveBtn = backdrop.querySelector("#study-save-btn");
            const skipBtn = backdrop.querySelector("#study-skip-btn");

            let settled = false;

            function onKeydown(e) {
                if (e.key === "Escape") close(null);
            }
            document.addEventListener("keydown", onKeydown);

            function close(result, immediate) {
                if (settled) return;
                settled = true;
                dismissActiveModal = null;
                document.removeEventListener("keydown", onKeydown);
                if (immediate) {
                    backdrop.remove();
                } else {
                    backdrop.classList.add("opacity-0");
                    modal.classList.add("scale-95", "opacity-0");
                    setTimeout(() => backdrop.remove(), 200);
                }
                resolve(result);
            }

            dismissActiveModal = () => close(null, true);

            slider.addEventListener("input", () => {
                scoreDisplay.textContent = slider.value;
            });

            backdrop.addEventListener("click", (e) => {
                if (e.target === backdrop) {
                    console.log("[study-tracker] Dismissed via backdrop for topic", topicId);
                    close(null);
                }
            });

            skipBtn.addEventListener("click", () => {
                console.log("[study-tracker] Skipped for topic", topicId);
                close(null);
            });

            saveBtn.addEventListener("click", async () => {
                const score = parseInt(slider.value, 10);
                const notes = notesEl.value.trim();

                saveBtn.disabled = true;
                skipBtn.disabled = true;
                saveBtn.textContent = "Saving...";
                feedbackEl.className = "hidden mb-4 text-sm rounded-xl px-3 py-2";

                try {
                    const res = await fetch(`${API}/api/topics/${topicId}/mark-reviewed`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ score, notes: notes || undefined }),
                    });

                    if (!res.ok) {
                        const body = await res.json().catch(() => ({}));
                        throw new Error(body.detail || `HTTP ${res.status}`);
                    }

                    const data = await res.json();
                    window.dispatchEvent(new Event("review-recorded"));

                    const pct = Math.round((data.mastery_updated || 0) * 100);
                    const days = daysUntil(data.next_review);
                    feedbackEl.textContent = `Mastery updated to ${pct}%, next review in ${days} day${days === 1 ? "" : "s"}`;
                    feedbackEl.className =
                        "mb-4 text-sm rounded-xl px-3 py-2 bg-green-500/10 text-green-500 border border-green-500/20";

                    launchConfetti(modal);
                    saveBtn.textContent = "Saved!";

                    setTimeout(() => close(data), 1400);
                } catch (err) {
                    console.error("[study-tracker] Failed to record review:", err);
                    feedbackEl.textContent = `Couldn't save: ${err.message}`;
                    feedbackEl.className =
                        "mb-4 text-sm rounded-xl px-3 py-2 bg-red-500/10 text-red-500 border border-red-500/20";
                    saveBtn.disabled = false;
                    skipBtn.disabled = false;
                    saveBtn.textContent = "Save & Continue";
                }
            });
        });
    }

    window.showStudyTracker = showStudyTracker;
})();
