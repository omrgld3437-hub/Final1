/**
 * FILE: components.js
 * VERSION: v2
 * DATE: 2025-01-21
 * CHANGE: Add P/L formatting helpers (fmtSignedUsd, fmtSignedPct, pnlClass) for project-wide use
 */

// Format utilities
const Format = {
    usd: (value, decimals = 2) => {
        if (value === null || value === undefined) return "$0.00";
        return `$${parseFloat(value).toFixed(decimals)}`;
    },
    
    percent: (value, decimals = 2) => {
        if (value === null || value === undefined) return "0.00%";
        const sign = parseFloat(value) >= 0 ? "+" : "";
        return `${sign}${parseFloat(value).toFixed(decimals)}%`;
    },
    
    number: (value, decimals = 0) => {
        if (value === null || value === undefined) return "0";
        return parseFloat(value).toLocaleString('en-US', {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals
        });
    },
    
    date: (dateString) => {
        if (!dateString) return "-";
        if (typeof window.trTime !== 'undefined' && window.trTime.trFormatDate)
            return window.trTime.trFormatDate(dateString);
        const date = new Date(dateString);
        return date.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric', timeZone: 'Europe/Istanbul' });
    },
    
    time: (dateString) => {
        if (!dateString) return "-";
        if (typeof window.trTime !== 'undefined' && window.trTime.trFormatTime)
            return window.trTime.trFormatTime(dateString);
        const date = new Date(dateString);
        return date.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', timeZone: 'Europe/Istanbul' });
    },
    
    relativeTime: (dateString) => {
        if (!dateString) return "-";
        const date = new Date(dateString);
        const now = new Date();
        const diffMs = now - date;
        const diffSecs = Math.floor(diffMs / 1000);
        const diffMins = Math.floor(diffSecs / 60);
        const diffHours = Math.floor(diffMins / 60);
        
        if (diffSecs < 60) return `${diffSecs}s önce`;
        if (diffMins < 60) return `${diffMins}dk önce`;
        if (diffHours < 24) return `${diffHours}sa önce`;
        return Format.date(dateString);
    }
};

// Create element helper
function createEl(tag, className = "", attributes = {}) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    Object.entries(attributes).forEach(([key, value]) => {
        if (key === "text" || key === "textContent") {
            el.textContent = value;
        } else if (key === "html" || key === "innerHTML") {
            el.innerHTML = value;
        } else if (key === "onclick" || key === "onclick") {
            el.onclick = value;
        } else {
            el.setAttribute(key, value);
        }
    });
    return el;
}

// Badge component
function createBadge(text, type = "neutral") {
    const badge = createEl("span", `badge ${type}`, { text });
    return badge;
}

// Toast notification system
const Toast = {
    container: null,
    _persistent: {},

    init() {
        if (!this.container) {
            this.container = createEl("div", "toast-container");
            document.body.appendChild(this.container);
        }
    },

    show(message, type = "info", duration = 3000) {
        this.init();
        const toast = createEl("div", `toast ${type}`, {
            text: message
        });

        this.container.appendChild(toast);

        if (duration == null || duration <= 0) return toast;

        setTimeout(() => {
            toast.style.animation = "slideIn 0.3s ease-out reverse";
            setTimeout(() => toast.remove(), 300);
        }, duration);
        return toast;
    },

    /** Kalıcı toast — dismiss(key) veya sunucu gelene kadar ekranda kalır. */
    showPersistent(key, message, type = "warning") {
        if (!key) return this.show(message, type, 0);
        this.init();
        var existing = this._persistent[key];
        if (existing && existing.isConnected) {
            existing.textContent = message;
            existing.className = `toast ${type} toast-persistent`;
            return existing;
        }
        var toast = createEl("div", `toast ${type} toast-persistent`, { text: message });
        this._persistent[key] = toast;
        this.container.appendChild(toast);
        return toast;
    },

    dismiss(key) {
        if (!key || !this._persistent[key]) return;
        var toast = this._persistent[key];
        delete this._persistent[key];
        if (!toast.isConnected) return;
        toast.style.animation = "slideIn 0.3s ease-out reverse";
        setTimeout(function () { toast.remove(); }, 300);
    },

    success(message, duration) {
        this.show(message, "success", duration != null ? duration : 3000);
    },

    error(message, duration) {
        this.show(message, "error", duration != null ? duration : 3000);
    },

    warning(message, duration) {
        this.show(message, "warning", duration != null ? duration : 3000);
    }
};

// Skeleton loader
function createSkeleton(width = "100%", height = "20px") {
    const skeleton = createEl("div", "skeleton");
    skeleton.style.width = width;
    skeleton.style.height = height;
    return skeleton;
}

// Empty state component
function createEmptyState(message = "No data available") {
    return createEl("div", "empty-state", { text: message });
}

// P/L formatting helpers (project-wide)
function pnlClass(x) {
    if (x > 0) return "pos";
    if (x < 0) return "neg";
    return "zero";
}

function fmtSignedUsd(x) {
    const num = parseFloat(x) || 0;
    const formatted = num.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (num > 0 ? "+" : "") + formatted;
}

function fmtSignedPct(x) {
    const num = parseFloat(x) || 0;
    const formatted = num.toFixed(2);
    return (num > 0 ? "+" : "") + formatted;
}

// In-flight guard helper
function createInFlightGuard() {
    let inFlight = false;
    return {
        check: () => !inFlight,
        set: (value) => { inFlight = value; },
        wrap: async (fn) => {
            if (inFlight) return;
            inFlight = true;
            try {
                return await fn();
            } finally {
                inFlight = false;
            }
        }
    };
}

// Export for use in other scripts
window.Format = Format;
window.createEl = createEl;
window.createBadge = createBadge;
window.Toast = Toast;
window.createSkeleton = createSkeleton;
window.createEmptyState = createEmptyState;
window.pnlClass = pnlClass;
window.fmtSignedUsd = fmtSignedUsd;
window.fmtSignedPct = fmtSignedPct;
window.createInFlightGuard = createInFlightGuard;

