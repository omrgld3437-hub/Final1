/**
 * Kullanıcı işlem geçmişi beacon — sayfa geçişleri ve vazgeçme olayları.
 * Teknik hata göndermez; sade olay bildirir.
 */
(function (global) {
    "use strict";

    var SESSION_KEY = "ua_beacon_session";
    var state = {
        page: null,
        symbol: null,
        budget: null,
        analysisStarted: false,
        analysisCompleted: false,
        paramApproved: false,
        botStartScreen: false,
        messageDraft: false,
    };

    function token() {
        try {
            return sessionStorage.getItem("token") || localStorage.getItem("token") || "";
        } catch (e) {
            return "";
        }
    }

    function send(payload) {
        var t = token();
        if (!t) return;
        try {
            fetch("/api/user-activity/beacon", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    Authorization: "Bearer " + t,
                },
                body: JSON.stringify(payload),
                keepalive: true,
            }).catch(function () {});
        } catch (e) {}
    }

    function pageView(page) {
        state.page = page;
        send({ event_type: "PAGE_VIEW", page: page });
    }

    function coinSelected(symbol) {
        state.symbol = symbol;
        send({
            event_type: "PARAM_COIN_SELECTED",
            page: "param-assistant",
            symbol: symbol,
        });
    }

    function budgetEntered(budget) {
        state.budget = budget;
        send({
            event_type: "PARAM_BUDGET_ENTERED",
            page: "param-assistant",
            budget: budget,
            symbol: state.symbol,
        });
    }

    function analysisStarted(symbol, budget) {
        state.analysisStarted = true;
        state.symbol = symbol || state.symbol;
        state.budget = budget || state.budget;
        send({
            event_type: "PARAM_ANALYSIS_STARTED",
            page: "param-assistant",
            symbol: state.symbol,
            budget: state.budget,
        });
    }

    function analysisCompleted(symbol, resultType) {
        state.analysisCompleted = true;
        var evt = "PARAM_ANALYSIS_COMPLETED";
        if (resultType === "deployable_grid") evt = "PARAM_RESULT_DEPLOYABLE";
        else if (resultType === "recommended_grid") evt = "PARAM_RESULT_RECOMMENDED";
        else if (resultType === "no_trade") evt = "PARAM_RESULT_NO_TRADE";
        else if (resultType === "failed") evt = "PARAM_ANALYSIS_FAILED";
        send({
            event_type: evt,
            page: "param-assistant",
            symbol: symbol || state.symbol,
        });
    }

    function paramApproved() {
        state.paramApproved = true;
        send({ event_type: "PARAM_APPROVED", page: "param-assistant", symbol: state.symbol });
    }

    function botStartScreen() {
        state.botStartScreen = true;
        pageView("dynamic-mode");
    }

    function messageDraft() {
        state.messageDraft = true;
    }

    function checkAbandonment() {
        if (state.page === "param-assistant") {
            if (state.symbol && !state.analysisStarted) {
                send({
                    event_type: "ABANDON",
                    abandonment: { type: "COIN_NO_ANALYSIS" },
                    symbol: state.symbol,
                });
            } else if (state.budget && !state.analysisStarted) {
                send({
                    event_type: "ABANDON",
                    abandonment: { type: "BUDGET_NO_ANALYSIS" },
                    budget: state.budget,
                });
            } else if (state.analysisCompleted && !state.paramApproved) {
                send({
                    event_type: "ABANDON",
                    abandonment: { type: "PARAM_NO_APPROVE" },
                    symbol: state.symbol,
                });
            }
        }
        if (state.page === "dynamic-mode" && state.botStartScreen) {
            send({ event_type: "ABANDON", abandonment: { type: "BOT_NO_START" } });
        }
        if (state.page === "support" && state.messageDraft) {
            send({ event_type: "ABANDON", abandonment: { type: "MESSAGE_UNSENT" } });
        }
    }

    function bindPageLeave() {
        global.addEventListener("beforeunload", checkAbandonment);
        global.addEventListener("pagehide", checkAbandonment);
    }

    global.UserActivityBeacon = {
        pageView: pageView,
        coinSelected: coinSelected,
        budgetEntered: budgetEntered,
        analysisStarted: analysisStarted,
        analysisCompleted: analysisCompleted,
        paramApproved: paramApproved,
        botStartScreen: botStartScreen,
        messageDraft: messageDraft,
        bindPageLeave: bindPageLeave,
    };

    bindPageLeave();
})(typeof window !== "undefined" ? window : globalThis);
