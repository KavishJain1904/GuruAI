/**
 * theme.js — Shared light / dark mode engine for GuruAI.
 * Include this script on every page with:  <script src="/theme.js"></script>
 * The theme toggle button should call window.toggleTheme() on click.
 */

(function () {
    /* ── 1. Inject shared light-mode CSS ───────────────────────────── */
    const LIGHT_CSS = `
        html[data-theme="light"] { color-scheme: light; }

        html[data-theme="light"],
        html[data-theme="light"] body {
            background-color: #f0ecf8 !important;
            color: #1a1126 !important;
        }

        /* ── Sidebar (all pages) ── */
        html[data-theme="light"] aside {
            background-color: #e8e0f5 !important;
            border-color: #cfc4e8 !important;
        }
        html[data-theme="light"] aside * { color: #2d2140 !important; }
        html[data-theme="light"] aside p,
        html[data-theme="light"] aside .text-xs { color: #6a5a8a !important; }
        html[data-theme="light"] aside nav a,
        html[data-theme="light"] aside nav div { color: #4a3a6a !important; }
        html[data-theme="light"] aside nav a:hover,
        html[data-theme="light"] aside nav div:hover { background: rgba(90,50,160,0.10) !important; color: #1a1126 !important; }
        html[data-theme="light"] aside nav a[class*="bg-[#1f1f22]"],
        html[data-theme="light"] aside nav div[class*="bg-[#1f1f22]"] { background: #d8ccf2 !important; color: #5b10b8 !important; }
        /* New session / CTA buttons keep their gradient text white */
        html[data-theme="light"] aside a.bg-glow-primary,
        html[data-theme="light"] aside button[onclick*="newSession"] { color: #fff !important; }

        /* ── Header (all pages) ── */
        html[data-theme="light"] header {
            background: rgba(232,224,245,0.96) !important;
            box-shadow: 0 2px 20px rgba(80,40,140,0.10) !important;
            border-bottom-color: #cfc4e8 !important;
        }
        html[data-theme="light"] header * { color: #3a2860 !important; }
        /* Brand gradient text */
        html[data-theme="light"] header .bg-clip-text {
            -webkit-text-fill-color: transparent !important;
            background: linear-gradient(135deg,#8b2ff8,#6a10e0) !important;
            -webkit-background-clip: text !important;
            background-clip: text !important;
            color: transparent !important;
        }
        html[data-theme="light"] header input {
            background: #d8ccf2 !important;
            color: #1a1126 !important;
        }
        html[data-theme="light"] header input::placeholder { color: #7a6a9a !important; }

        /* ── Main / body area ── */
        html[data-theme="light"] main,
        html[data-theme="light"] #scroll-area,
        html[data-theme="light"] #study-view,
        html[data-theme="light"] #chat-feed { background: #f0ecf8 !important; }

        /* ── Surface containers ── */
        html[data-theme="light"] [class*="bg-surface-container-highest"] { background: #d8ccf2 !important; color: #1a1126 !important; }
        html[data-theme="light"] [class*="bg-surface-container-high"]    { background: #e2d8f7 !important; color: #1a1126 !important; }
        html[data-theme="light"] [class*="bg-surface-container-low"]     { background: #e8e2fb !important; color: #1a1126 !important; }
        html[data-theme="light"] [class*="bg-surface-container-lowest"]  { background: #d8ccf2 !important; color: #1a1126 !important; }
        html[data-theme="light"] [class*="bg-surface-container"]         { background: #ece7fb !important; color: #1a1126 !important; }
        html[data-theme="light"] [class*="bg-surface-bright"]            { background: #ddd4f5 !important; }

        /* ── Generic text tokens ── */
        html[data-theme="light"] [class*="text-on-surface"]:not([class*="variant"]) { color: #1a1126 !important; }
        html[data-theme="light"] [class*="text-on-surface-variant"] { color: #6b5a8a !important; }
        html[data-theme="light"] [class*="text-outline"] { color: #9888b5 !important; }

        /* ── Generic button hover fix in light mode ── */
        html[data-theme="light"] button:not(#theme-toggle):not(.quiz-option):not([class*="bg-gradient"]):hover,
        html[data-theme="light"] a[class*="rounded"]:hover {
            opacity: 0.85;
        }
        html[data-theme="light"] [class*="hover:bg-surface-bright"]:hover { background: #cfc4e8 !important; }
        html[data-theme="light"] [class*="hover:bg-surface-container-high"]:hover { background: #d5ccf0 !important; }
        html[data-theme="light"] [class*="hover:text-primary"]:hover { color: #7020c8 !important; }
        html[data-theme="light"] [class*="hover:text-[#d095ff]"]:hover { color: #7020c8 !important; }
        html[data-theme="light"] [class*="hover:text-[#f6f3f5]"]:hover { color: #1a1126 !important; }

        /* ── Chat bubbles (index.html) ── */
        html[data-theme="light"] .ai-bubble {
            background: #ffffff !important;
            color: #1a1126 !important;
            border-left: 2px solid rgba(100,30,200,0.30) !important;
            box-shadow: 0 2px 14px rgba(80,40,140,0.08) !important;
        }
        html[data-theme="light"] .ai-bubble,
        html[data-theme="light"] .ai-bubble p,
        html[data-theme="light"] .ai-bubble span,
        html[data-theme="light"] .ai-bubble li,
        html[data-theme="light"] .ai-bubble ul,
        html[data-theme="light"] .ai-bubble ol,
        html[data-theme="light"] .ai-bubble h1,
        html[data-theme="light"] .ai-bubble h2,
        html[data-theme="light"] .ai-bubble h3,
        html[data-theme="light"] .ai-bubble h4,
        html[data-theme="light"] .ai-bubble em,
        html[data-theme="light"] .ai-bubble blockquote,
        html[data-theme="light"] .ai-bubble td,
        html[data-theme="light"] .ai-bubble th { color: #1a1126 !important; }
        html[data-theme="light"] .ai-bubble strong { color: #3a006a !important; }
        html[data-theme="light"] .ai-bubble a { color: #6010b8 !important; }
        html[data-theme="light"] .ai-bubble code { background: #ebe4fa !important; color: #4a009a !important; }
        html[data-theme="light"] .ai-bubble pre  { background: #ebe4fa !important; color: #1a1126 !important; }

        html[data-theme="light"] .user-bubble {
            background: #d8ccf2 !important;
            color: #1a1126 !important;
        }
        html[data-theme="light"] .user-bubble * { color: #1a1126 !important; }

        /* ── Session list buttons ── */
        html[data-theme="light"] .session-btn { color: #5a4a7a !important; background: transparent !important; }
        html[data-theme="light"] .session-btn:hover { background: rgba(90,50,160,0.09) !important; color: #1a1126 !important; }
        html[data-theme="light"] .session-btn.active { background: #d8ccf2 !important; color: #5b10b8 !important; font-weight: 700 !important; }

        /* ── Active nav pills ── */
        html[data-theme="light"] #nav-study,
        html[data-theme="light"] #nav-memory { background-color: #d8ccf2 !important; color: #5b10b8 !important; }
        html[data-theme="light"] #nav-study *,
        html[data-theme="light"] #nav-memory * { color: #5b10b8 !important; }

        /* ── Quiz (both index and topic pages) ── */
        html[data-theme="light"] .quiz-question {
            background: #ffffff !important;
            box-shadow: 0 2px 10px rgba(80,40,140,0.08) !important;
        }
        html[data-theme="light"] .quiz-question p,
        html[data-theme="light"] .quiz-question strong,
        html[data-theme="light"] .quiz-question em { color: #1a1126 !important; }
        html[data-theme="light"] .quiz-option {
            background: #ede8fb !important;
            border-color: #c4b8e0 !important;
            color: #1a1126 !important;
        }
        html[data-theme="light"] .quiz-option:hover:not(:disabled) {
            background: #ddd4f5 !important;
            border-color: #7020c8 !important;
            color: #1a1126 !important;
        }
        html[data-theme="light"] .quiz-explanation {
            background: #e8e2fb !important;
            color: #4a3a6a !important;
            border-left-color: #9060e0 !important;
        }
        html[data-theme="light"] .quiz-feed-card [class*="bg-surface-container-high"] { background: #e2d8f7 !important; }
        html[data-theme="light"] .quiz-feed-card * { color: #1a1126 !important; }

        /* ── topic.html prose area ── */
        html[data-theme="light"] .prose { color: #1a1126 !important; }
        html[data-theme="light"] .prose h1 { color: #1a1126 !important; }
        html[data-theme="light"] .prose h2 { color: #6b10d8 !important; border-bottom-color: rgba(107,16,216,0.15) !important; }
        html[data-theme="light"] .prose h3 { color: #2d1a50 !important; }
        html[data-theme="light"] .prose p,
        html[data-theme="light"] .prose li { color: #2d2140 !important; }
        html[data-theme="light"] .prose strong { color: #1a1126 !important; }
        html[data-theme="light"] .prose em { color: #6b10d8 !important; }
        html[data-theme="light"] .prose code { background: #e4d8f8 !important; color: #4a009a !important; }
        html[data-theme="light"] .prose pre { background: #e8e2fb !important; border-color: #cfc4e8 !important; }
        html[data-theme="light"] .prose pre code { color: #4a009a !important; }
        html[data-theme="light"] .prose blockquote { background: rgba(107,16,216,0.05) !important; border-left-color: #8b2ff8 !important; }

        /* ── topic.html skeleton loader in light ── */
        html[data-theme="light"] .skeleton {
            background: linear-gradient(90deg, #e0d8f5 25%, #d4caf0 50%, #e0d8f5 75%) !important;
            background-size: 1000px 100% !important;
        }

        /* ── knowledge.html folder cards ── */
        html[data-theme="light"] #folders-grid [class*="bg-surface-container"] {
            background: #ece7fb !important;
            border-color: #cfc4e8 !important;
        }
        html[data-theme="light"] #folders-grid [class*="bg-surface-container"]:hover {
            background: #e2d8f7 !important;
            border-color: rgba(112,32,200,0.40) !important;
        }
        html[data-theme="light"] #folders-grid * { color: #1a1126 !important; }
        html[data-theme="light"] #folders-grid .text-error { color: #c0364a !important; }
        html[data-theme="light"] #folders-grid .text-secondary { color: #007a88 !important; }
        html[data-theme="light"] #folders-grid .text-tertiary { color: #006830 !important; }

        /* ── knowledge.html details columns ── */
        html[data-theme="light"] #details-view [class*="bg-surface-container"] {
            background: #ece7fb !important;
            border-color: #cfc4e8 !important;
        }
        html[data-theme="light"] #details-view [class*="bg-surface-container-high"] {
            background: #e2d8f7 !important;
        }
        html[data-theme="light"] #details-view [class*="bg-surface-container-highest"] {
            background: #d8ccf2 !important;
        }
        html[data-theme="light"] #details-view * { color: #1a1126 !important; }
        html[data-theme="light"] #strong-column-content *, html[data-theme="light"] .text-tertiary { color: #006830 !important; }
        html[data-theme="light"] #average-column-content *, html[data-theme="light"] .text-secondary { color: #007a88 !important; }
        html[data-theme="light"] #weak-column-content *,   html[data-theme="light"] .text-error     { color: #c0364a !important; }

        /* ── Memory view (index.html) ── */
        html[data-theme="light"] #memory-view > div:first-child {
            background: rgba(232,224,245,0.96) !important;
            border-bottom-color: #cfc4e8 !important;
        }
        html[data-theme="light"] #memory-view > div:first-child * { color: #2d2140 !important; }
        html[data-theme="light"] #memory-chat-feed { background: #f0ecf8 !important; }
        html[data-theme="light"] #chat-input,
        html[data-theme="light"] #memory-chat-input { color: #1a1126 !important; caret-color: #7020c8 !important; }
        html[data-theme="light"] #chat-input::placeholder,
        html[data-theme="light"] #memory-chat-input::placeholder { color: #8878a8 !important; }

        /* ── DB status pill ── */
        html[data-theme="light"] [class*="bg-surface-bright\\/"] { background: #ddd4f5 !important; }
        html[data-theme="light"] [class*="text-on-surface\\/60"] { color: #6a5a8a !important; }

        /* ── Scrollbar ── */
        html[data-theme="light"] ::-webkit-scrollbar-thumb { background: #c4b8e0; }
        html[data-theme="light"] ::-webkit-scrollbar-thumb:hover { background: #a898cc; }

        /* ── Theme toggle button ── */
        #theme-toggle-shared {
            width: 38px; height: 38px; border-radius: 50%;
            border: 2px solid rgba(208,149,255,0.40);
            background: rgba(208,149,255,0.10);
            color: #c57eff;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: all 0.22s ease; flex-shrink: 0;
        }
        #theme-toggle-shared:hover {
            background: rgba(208,149,255,0.22); border-color: #d095ff; color: #e0b0ff;
            transform: rotate(15deg) scale(1.08);
            box-shadow: 0 0 14px rgba(208,149,255,0.35);
        }
        #theme-toggle-shared .material-symbols-outlined {
            font-size: 20px;
            font-variation-settings: 'FILL' 1,'wght' 400,'GRAD' 0,'opsz' 24;
        }
        html[data-theme="light"] #theme-toggle-shared {
            border-color: rgba(100,30,200,0.30);
            background: rgba(100,30,200,0.08);
            color: #6010b8;
        }
        html[data-theme="light"] #theme-toggle-shared:hover {
            background: rgba(100,30,200,0.16); border-color: #7020c8; color: #5000a0;
            box-shadow: 0 0 14px rgba(100,30,200,0.25);
        }
    `;

    const styleEl = document.createElement('style');
    styleEl.id = 'scholar-theme-styles';
    document.head.appendChild(styleEl);
    styleEl.textContent = LIGHT_CSS;

    /* ── 2. Apply stored theme immediately (before paint) ─────────── */
    function applyStoredTheme() {
        const stored = localStorage.getItem('scholar-theme');
        if (stored === 'light') _enableLight(false);
    }

    /* ── 3. Core enable/disable ───────────────────────────────────── */
    function _enableLight(save) {
        document.documentElement.setAttribute('data-theme', 'light');
        _updateIcon('wb_sunny');
        _patchInlineColors(true);
        if (save) localStorage.setItem('scholar-theme', 'light');
    }

    function _enableDark(save) {
        document.documentElement.removeAttribute('data-theme');
        _updateIcon('dark_mode');
        _patchInlineColors(false);
        if (save) localStorage.setItem('scholar-theme', 'dark');
    }

    /* ── 4. Patch elements with hardcoded Tailwind arbitrary values ── */
    function _patchInlineColors(isLight) {
        // Sidebars: bg-[#131315]
        document.querySelectorAll('aside').forEach(el => {
            el.style.backgroundColor = isLight ? '#e8e0f5' : '';
        });
        // Headers: bg-[#131315] or bg-[#0e0e10]/80
        document.querySelectorAll('header').forEach(el => {
            el.style.backgroundColor = isLight ? 'rgba(232,224,245,0.96)' : '';
        });
        // bg-[#1f1f22] active pills / cards
        document.querySelectorAll('[class*="bg-[#1f1f22]"]').forEach(el => {
            el.style.backgroundColor = isLight ? '#d8ccf2' : '';
        });
        // Memory view / inner header bg-[#0e0e10]
        const memH = document.querySelector('#memory-view > div:first-child');
        if (memH) memH.style.backgroundColor = isLight ? 'rgba(232,224,245,0.96)' : '';
        // Text that's hardcoded text-[#f6f3f5]
        document.querySelectorAll('[class*="text-[#f6f3f5]"]').forEach(el => {
            el.style.color = isLight ? '#2d2140' : '';
        });
        // Hardcoded text-[#f6f3f5]/60 or /40
        document.querySelectorAll('[class*="text-[#f6f3f5]/"]').forEach(el => {
            el.style.color = isLight ? '#6a5a8a' : '';
        });
        // Hardcoded text-[#d095ff] level badge in sidebar
        document.querySelectorAll('[class*="text-[#d095ff]"]').forEach(el => {
            el.style.color = isLight ? '#7020c8' : '';
        });
    }

    /* ── 5. Update icon on all toggle buttons ─────────────────────── */
    function _updateIcon(name) {
        ['theme-icon', 'theme-icon-shared'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = name;
        });
    }

    /* ── 6. Public API ────────────────────────────────────────────── */
    window.toggleTheme = function () {
        const isLight = document.documentElement.getAttribute('data-theme') === 'light';
        if (isLight) _enableDark(true); else _enableLight(true);
    };

    window.enableLight = function () { _enableLight(true); };
    window.enableDark  = function () { _enableDark(true); };

    /* ── 7. Boot ──────────────────────────────────────────────────── */
    // Run immediately for elements already in DOM, then again after DOM ready
    applyStoredTheme();
    document.addEventListener('DOMContentLoaded', () => {
        applyStoredTheme(); // re-patch newly-rendered DOM elements
    });
})();
