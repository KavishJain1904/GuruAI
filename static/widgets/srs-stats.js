/**
 * srs-stats.js — Dashboard statistics panel for the SRS feature.
 *
 * Include with:  <script src="/widgets/srs-stats.js"></script>
 * Mount with:    initSrsStatsWidget('srs-stats-widget')
 * (the target container element must already exist in the DOM)
 *
 * Uses Tabler icon webfont classes (<i class="ti ti-NAME">). This file lazily
 * injects the Tabler icons stylesheet if the host page hasn't already loaded it.
 *
 * Backend contract: GET /api/topics/statistics
 * See server.py + src/personalization/tracker.py for the response shape.
 */
(function () {
    const API = "";
    const REFRESH_MS = 5 * 60 * 1000; // 5 minutes
    const TABLER_CSS_URL = "https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/dist/tabler-icons.min.css";

    let containerEl = null;
    let refreshTimer = null;
    let lastUpdated = null;
    let latestRequestId = 0;

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function ensureTablerIconsLoaded() {
        if (document.getElementById("tabler-icons-css")) return;
        const link = document.createElement("link");
        link.id = "tabler-icons-css";
        link.rel = "stylesheet";
        link.href = TABLER_CSS_URL;
        document.head.appendChild(link);
        console.log("[srs-stats] Injected Tabler icons stylesheet");
    }

    function formatMinutesAgo(date) {
        if (!date) return "";
        const mins = Math.max(0, Math.round((Date.now() - date.getTime()) / 60000));
        if (mins < 1) return "Last updated: just now";
        if (mins === 1) return "Last updated: 1 minute ago";
        return `Last updated: ${mins} minutes ago`;
    }

    function renderLoadingStats() {
        if (!containerEl) return;
        containerEl.innerHTML = `
            <div class="bg-surface-container rounded-2xl border border-outline-variant/10 p-6 flex items-center justify-center gap-3 text-on-surface-variant">
                <span class="w-5 h-5 border-2 border-primary/30 border-t-primary rounded-full animate-spin"></span>
                <span class="text-sm">Loading statistics...</span>
            </div>
        `;
    }

    function renderStatsError(message) {
        if (!containerEl) return;
        containerEl.innerHTML = `
            <div class="bg-surface-container rounded-2xl border border-error/30 p-6 text-center">
                <p class="text-error text-sm font-medium">Couldn't load your statistics.</p>
                <p class="text-on-surface-variant text-xs mt-1">${escapeHtml(message)}</p>
                <button id="srs-stats-retry"
                    class="mt-3 text-xs px-3 py-1.5 rounded-full bg-surface-container-high border border-outline-variant/20 text-on-surface hover:bg-surface-container-highest transition-colors">
                    Retry
                </button>
            </div>
        `;
        const retryBtn = document.getElementById("srs-stats-retry");
        if (retryBtn) retryBtn.addEventListener("click", loadStats);
    }

    function renderStatCard(card) {
        return `
            <div class="bg-surface-container rounded-2xl border border-outline-variant/10 p-4 flex items-center gap-4">
                <div class="w-10 h-10 rounded-xl bg-surface-container-high flex items-center justify-center flex-shrink-0">
                    <i class="ti ${card.icon} text-xl ${card.color}"></i>
                </div>
                <div class="min-w-0">
                    <p class="text-on-surface-variant text-xs">${escapeHtml(card.label)}</p>
                    <p class="text-on-surface font-semibold text-base truncate">${escapeHtml(String(card.value))}</p>
                    ${card.sub ? `<p class="text-on-surface-variant/70 text-xs truncate">${escapeHtml(card.sub)}</p>` : ""}
                </div>
            </div>
        `;
    }

    /** Renders the fetched statistics payload as a responsive card grid. */
    function renderStatsGrid(data) {
        if (!containerEl) return;
        lastUpdated = new Date();
        ensureTablerIconsLoaded();

        const avgPct = Math.round((data.avg_mastery || 0) * 100);
        const overdue = data.topics_overdue || 0;

        const cards = [
            { label: "Total Topics", value: data.total_topics ?? 0, icon: "ti-book", color: "text-primary" },
            { label: "Topics Due Today", value: data.topics_due ?? 0, icon: "ti-calendar", color: "text-secondary" },
            {
                label: "Overdue Topics",
                value: overdue,
                icon: "ti-alert-triangle",
                color: overdue > 0 ? "text-red-500" : "text-on-surface-variant",
            },
            { label: "Average Mastery", value: `${avgPct}%`, icon: "ti-chart-bar", color: "text-green-500" },
            {
                label: "Strongest Topic",
                value: data.strongest_topic || "—",
                sub: data.strongest_mastery != null ? `${data.strongest_subject ? `${data.strongest_subject} · ` : ""}${Math.round(data.strongest_mastery * 100)}% mastery` : null,
                icon: "ti-trophy",
                color: "text-yellow-500",
            },
            {
                label: "Weakest Topic",
                value: data.weakest_topic || "—",
                sub: data.weakest_mastery != null ? `${data.weakest_subject ? `${data.weakest_subject} · ` : ""}${Math.round(data.weakest_mastery * 100)}% mastery` : null,
                icon: "ti-target",
                color: "text-red-500",
            },
        ];

        containerEl.innerHTML = `
            <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                ${cards.map(renderStatCard).join("")}
            </div>
            <p id="srs-stats-updated" class="text-on-surface-variant/60 text-[11px] mt-2 text-right">${formatMinutesAgo(lastUpdated)}</p>
        `;
    }

    /** Fetches the SRS dashboard statistics and renders them. */
    async function loadStats() {
        const requestId = ++latestRequestId;
        renderLoadingStats();
        console.log("[srs-stats] Fetching", `${API}/api/topics/statistics`);

        try {
            const res = await fetch(`${API}/api/topics/statistics`);
            if (!res.ok) {
                const body = await res.json().catch(() => ({}));
                throw new Error(body.detail || `HTTP ${res.status}`);
            }
            const data = await res.json();
            if (requestId !== latestRequestId) return;
            console.log("[srs-stats] Loaded", data);
            renderStatsGrid(data);
        } catch (err) {
            if (requestId !== latestRequestId) return;
            console.error("[srs-stats] Failed to load statistics:", err);
            renderStatsError(err.message || "Unknown error");
        }
    }

    /** Mounts the widget into the given container id, starts auto-refresh. */
    function initSrsStatsWidget(containerId = "srs-stats-widget") {
        containerEl = document.getElementById(containerId);
        if (!containerEl) {
            console.error(`[srs-stats] Container #${containerId} not found in DOM.`);
            return;
        }

        ensureTablerIconsLoaded();
        loadStats();

        if (refreshTimer) clearInterval(refreshTimer);
        refreshTimer = setInterval(loadStats, REFRESH_MS);
    }

    // Expose the widget's public API for main.js / inline handlers.
    window.initSrsStatsWidget = initSrsStatsWidget;
    window.loadStats = loadStats;
    window.renderStatsGrid = renderStatsGrid;
})();
