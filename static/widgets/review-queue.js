/**
 * review-queue.js — "Topics to Review Today" widget for the SRS feature.
 *
 * Include with:  <script src="/widgets/review-queue.js"></script>
 * Mount with:    initReviewQueueWidget('review-queue-widget')
 * (the target container element must already exist in the DOM)
 *
 * Backend contract: GET /api/suggestions/review-queue?category=&sort=&limit=
 * See server.py + src/personalization/tracker.py for the response shape.
 */
(function () {
    const API = "";
    const REFRESH_MS = 10 * 60 * 1000; // 10 minutes
    const TICK_MS = 30 * 1000; // refresh the "last updated" label
    const LIMIT = 10;

    let containerEl = null;
    let refreshTimer = null;
    let tickTimer = null;
    let lastUpdated = null;
    let latestRequestId = 0;
    let currentCategory = "all";
    let currentSort = "urgent";

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    // Use the server's category so UI colors cannot drift from its thresholds.
    function getColorClass(category) {
        return { Weak: "text-red-500", Average: "text-yellow-500", Strong: "text-green-500" }[category] || "text-on-surface-variant";
    }

    function getDotClass(category) {
        return { Weak: "bg-red-500", Average: "bg-yellow-500", Strong: "bg-green-500" }[category] || "bg-gray-500";
    }

    function formatDaysUntil(days) {
        if (days === 0) return "Due today";
        if (days < 0) return `Overdue by ${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"}`;
        return `Due in ${days} day${days === 1 ? "" : "s"}`;
    }

    function formatMinutesAgo(date) {
        if (!date) return "";
        const mins = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
        if (mins < 1) return "Last updated: just now";
        if (mins === 1) return "Last updated: 1 minute ago";
        return `Last updated: ${mins} minutes ago`;
    }

    function renderLoading() {
        if (!containerEl) return;
        containerEl.innerHTML = `
            <div class="bg-surface-container rounded-2xl border border-outline-variant/10 p-6 flex items-center justify-center gap-3 text-on-surface-variant">
                <span class="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
                <span class="text-sm">Loading review queue...</span>
            </div>
        `;
    }

    function renderErrorState(message) {
        if (!containerEl) return;
        containerEl.innerHTML = `
            <div class="bg-surface-container rounded-2xl border border-error/30 p-6 text-center">
                <p class="text-error text-sm font-medium">Couldn't load your review queue.</p>
                <p class="text-on-surface-variant text-xs mt-1">${escapeHtml(message)}</p>
                <button id="review-queue-retry"
                    class="mt-3 text-xs px-3 py-1.5 rounded-full bg-surface-container-high border border-outline-variant/20 text-on-surface hover:bg-surface-container-highest transition-colors">
                    Retry
                </button>
            </div>
        `;
        const retryBtn = document.getElementById("review-queue-retry");
        if (retryBtn) {
            retryBtn.addEventListener("click", () => loadReviewQueue(currentCategory, currentSort));
        }
    }

    function topicUrl(topic) {
        const params = new URLSearchParams({
            topic: topic.topic, subject: topic.subject,
            topic_id: String(topic.id),
            level: topic.mastery_category.toLowerCase(), score: String(Math.round(topic.mastery_level * 100)),
        });
        return `/topic.html?${params}`;
    }

    function renderTopicRow(topic) {
        const dueLabel = formatDaysUntil(topic.days_until_review);
        const dueClass = topic.days_until_review < 0 ? "text-red-500" : "text-on-surface-variant";
        return `
            <div class="px-5 py-3 flex items-center gap-3 hover:bg-surface-container-high/50 transition-colors">
                <span class="w-2 h-2 rounded-full flex-shrink-0 ${getDotClass(topic.mastery_category)}"></span>
                <button
                    data-topic-link
                    data-topic-url="${escapeHtml(topicUrl(topic))}"
                    class="flex-1 min-w-0 text-left">
                    <p class="text-on-surface text-sm font-medium truncate">${escapeHtml(topic.topic)}</p>
                    <p class="text-xs text-on-surface-variant/70 truncate">${escapeHtml(topic.subject)}</p>
                    <p class="text-xs ${dueClass}">
                        ${dueLabel}
                        <span class="text-on-surface-variant/50"> &middot; </span>
                        <span class="${getColorClass(topic.mastery_category)}">${escapeHtml(topic.mastery_category)}</span>
                    </p>
                </button>
                <button
                    data-study-btn
                    data-topic-id="${topic.id}"
                    data-topic-name="${escapeHtml(topic.topic)}"
                    class="flex-shrink-0 text-xs font-medium px-3 py-1.5 rounded-full bg-primary/10 text-primary hover:bg-primary/20 transition-colors">
                    Study Now
                </button>
            </div>
        `;
    }

    /** Renders the fetched review-queue payload into the widget container. */
    function renderTopics(data) {
        if (!containerEl) return;
        lastUpdated = new Date();

        const queue = (data && data.queue) || [];
        const dueCount = queue.length;
        const overdue = data && typeof data.overdue_count === "number" ? data.overdue_count : 0;

        const listHtml = queue.length
            ? queue.map(renderTopicRow).join("")
            : `
                <div class="py-10 px-5 text-center">
                    <p class="text-2xl mb-2">🎉</p>
                    <p class="text-on-surface font-medium text-sm">No topics due today! Keep up the great work!</p>
                </div>
            `;

        containerEl.innerHTML = `
            <div class="bg-surface-container rounded-2xl border border-outline-variant/10 overflow-hidden">
                <div class="px-5 py-4 border-b border-outline-variant/10 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-1">
                    <div class="min-w-0">
                        <h3 class="text-on-surface font-semibold text-base">Topics to Review Today</h3>
                        <p class="text-on-surface-variant text-xs mt-0.5">${dueCount} topic${dueCount === 1 ? "" : "s"} due, ${overdue} overdue</p>
                    </div>
                    <span id="review-queue-updated" class="text-on-surface-variant/60 text-[11px] flex-shrink-0">${formatMinutesAgo(lastUpdated)}</span>
                </div>
                <div class="divide-y divide-outline-variant/10">
                    ${listHtml}
                </div>
            </div>
        `;

        containerEl.querySelectorAll("[data-topic-link]").forEach((el) => {
            el.addEventListener("click", () => {
                window.location.href = el.dataset.topicUrl;
            });
        });

        queue.forEach(setupStudyButton);
    }

    /** Wires the "Study Now" button for one topic to open the study-tracker modal. */
    function setupStudyButton(topic) {
        const { id: topicId, topic: topicName } = topic;
        if (!containerEl) return;
        const btn = containerEl.querySelector(`[data-study-btn][data-topic-id="${topicId}"]`);
        if (!btn) return;

        btn.addEventListener("click", async () => {
            if (typeof window.showStudyTracker !== "function") {
                console.error("[review-queue] showStudyTracker() unavailable — is study-tracker.js loaded?");
                window.location.href = topicUrl(topic);
                return;
            }
            try {
                const result = await window.showStudyTracker(topicId, topicName);
                console.log("[review-queue] Study session result for", topicName, result);
                // Successful saves dispatch review-recorded; the dashboard refreshes
                // both this queue and its statistics through that one event.
            } catch (err) {
                console.error("[review-queue] Study tracker failed:", err);
            }
        });
    }

    /** Fetches the review queue and renders it. */
    async function loadReviewQueue(category = "all", sort = "urgent") {
        currentCategory = category;
        currentSort = sort;
        const requestId = ++latestRequestId;
        renderLoading();

        const url = `${API}/api/suggestions/review-queue?category=${encodeURIComponent(category)}&sort=${encodeURIComponent(sort)}&limit=${LIMIT}`;
        console.log("[review-queue] Fetching", url);

        try {
            const res = await fetch(url);
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (requestId !== latestRequestId) return;
            console.log("[review-queue] Loaded", data);
            renderTopics(data);
        } catch (err) {
            if (requestId !== latestRequestId) return;
            console.error("[review-queue] Failed to load review queue:", err);
            renderErrorState(err.message || "Unknown error");
        }
    }

    /** Mounts the widget into the given container id, starts auto-refresh. */
    function initReviewQueueWidget(containerId = "review-queue-widget", options = {}) {
        containerEl = document.getElementById(containerId);
        if (!containerEl) {
            console.error(`[review-queue] Container #${containerId} not found in DOM.`);
            return;
        }

        currentCategory = options.category || "all";
        currentSort = options.sort || "urgent";

        loadReviewQueue(currentCategory, currentSort);

        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(() => loadReviewQueue(currentCategory, currentSort), REFRESH_MS);

        if (tickTimer) clearInterval(tickTimer);
        tickTimer = setInterval(() => {
            const el = document.getElementById("review-queue-updated");
            if (el) el.textContent = formatMinutesAgo(lastUpdated);
        }, TICK_MS);
    }

    // Expose the widget's public API for main.js / inline handlers.
    window.initReviewQueueWidget = initReviewQueueWidget;
    window.loadReviewQueue = loadReviewQueue;
    window.refreshReviewQueue = () => loadReviewQueue(currentCategory, currentSort);
    window.renderTopics = renderTopics;
    window.getColorClass = getColorClass;
    window.setupStudyButton = setupStudyButton;
})();
