const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('ui/assets/utils/dynamicModeParamsView.js', 'utf8');

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

const context = {
    window: {},
    escapeHtml,
    console,
    setTimeout,
    clearTimeout,
};
vm.createContext(context);
vm.runInContext(source, context);

const view = context.window.DynModeParamsView;
assert.ok(view, 'DynModeParamsView must be exported');

const html = view.renderBotDetailDynamicTab(
    {
        enabled: true,
        active: true,
        snapshot: {
            cycle_id: 7,
            regime: 'R5',
            data_fresh: true,
            applied: {
                base_alloc_pct: 63,
                quote_alloc_pct: 37,
                sell_trigger_trailing_pct: 0.8,
                buy_trigger_trailing_pct: 0.6,
                profit_exit_rise_pct: 1.5,
                profit_exit_drop_pct: 0.7,
                profit_reentry_drop_pct: 1.2,
                profit_reentry_rise_pct: 0.5,
                sell_grids: [
                    { sell_grid_pct: 1.5, sell_qty_pct_of_base: 100 },
                ],
                buy_grids: [
                    { buy_grid_pct: 1, buy_qty_pct_of_quote: 40 },
                    { buy_grid_pct: 2, buy_qty_pct_of_quote: 60 },
                ],
            },
            multiplier: {
                contract_version: 1,
                direction_scores: { up: 0.8, down: 0.2 },
                confidence: { effective: 0.75 },
                multipliers: {
                    base_alloc: 1.15,
                    quote_alloc: 0.85,
                    buy_distance: 1.2,
                    sell_distance: 0.9,
                    buy_trailing: 1.1,
                    sell_trailing: 0.95,
                },
                grid_count_invariant: {
                    buy_initial: 2,
                    sell_initial: 1,
                    buy_applied: 2,
                    sell_applied: 1,
                    preserved: true,
                },
            },
        },
    },
    { cycle_id: 7 },
    'SOLUSDT',
    {
        dynamic_mode: true,
        initial_capital_usdt: 50,
        reference_price: 75,
        base_alloc_pct: 55,
        quote_alloc_pct: 45,
    },
    {}
);

assert.ok(html.includes('Rejim çarpanları'));
assert.ok(html.includes('Yukarı yön kanıtı'));
assert.ok(html.includes('×1.20 / ×0.90'));
assert.ok(html.includes('2 / 1 · sabit'));
assert.ok(html.includes('Grid sayısı'));
assert.ok(!html.includes('paramRow'));

console.log('dynamicModeParamsView: multiplier render passed');
