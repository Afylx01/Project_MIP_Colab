/*
 * sim_kernel.c - Ultra-High-Performance C99 Simulation Kernel for Project MIP
 * Target Architecture: aarch64 (Qualcomm Snapdragon 8 Gen 2 / ARMv8.2-A + FP16 + NEON)
 * Termux PRoot Zero-Syscall Native Shared Library
 *
 * Upgraded capabilities:
 * 1. Multi-Schedule Rebalancing: Weekly, Monthly, Quarterly, Half-Yearly, Yearly
 * 2. Timeframe Window Slicing: Macro Eras & Random Rolling Windows
 * 3. Strategy Parameter ON/OFF Toggles (Filter Ablation bitmasks)
 * 4. Portfolio Sizes: N in {5, 10, 15, 20, 25, 30}
 * 5. Position Sizing Modes: ATR Risk Parity vs Equal Weight (1/N)
 * 6. Annualized Portfolio Turnover (%)
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <string.h>
#include <pthread.h>
#include <stdatomic.h>
#include <math.h>

#define MAX_UNIVERSE_SYMBOLS 2048
#define MAX_SECTORS 64
#define MAX_HOLDINGS 128
#define MAX_SCHEDULES 7
#define MAX_PERIODS 4096
#define CHUNK_SIZE 64

// Filter Flag Bitmasks
#define FILTER_RETRACE       (1 << 0) // 0x01: Retrace filter active
#define FILTER_TREND         (1 << 1) // 0x02: Trend EMA filter active
#define FILTER_RS            (1 << 2) // 0x04: Relative Strength filter active
#define FILTER_REGIME        (1 << 3) // 0x08: Benchmark regime filter active
#define FILTER_SECTOR_CAP    (1 << 4) // 0x10: Sector cap active
#define FILTER_RESIDUAL_MOM  (1 << 5) // 0x20: Residual momentum mode active
#define FILTER_VOL_TARGETING (1 << 6) // 0x40: Volatility targeting cash shield active
#define FILTER_DELIVERY_VETO (1 << 7) // 0x80: Delivery flow distribution veto active

// Output Simulation Summary Struct (Exactly 48 bytes, naturally aligned)
typedef struct {
    uint32_t param_id;        // 0
    float    cagr;            // 4
    float    sharpe;          // 8
    float    sortino;         // 12
    float    max_drawdown;    // 16
    float    calmar;          // 20
    float    win_rate;        // 24
    float    profit_factor;   // 28
    float    ending_equity;   // 32
    uint32_t total_trades;    // 36
    uint32_t winning_trades;  // 40
    float    turnover_annual; // 44: Annualized portfolio turnover %
} SimulationSummary;

// Simulation Parameter Specification (Exactly 64 bytes, naturally aligned)
typedef struct {
    uint32_t param_id;           // 0: Unique identifier
    uint32_t schedule_idx;       // 4: 0=weekly, 1=monthly, 2=quarterly, 3=half-yearly, 4=yearly
    uint32_t start_date_idx;     // 8: Start session index (0 = earliest)
    uint32_t end_date_idx;       // 12: End session index (0 = latest / T-1)
    uint32_t lookback_idx;       // 16: Index into lookback array
    uint32_t ema_idx;            // 20: Index into EMA spans array
    uint32_t top_n;              // 24: Top N stocks (5, 10, 15, 20)
    uint32_t exit_buffer_rank;   // 28: Exit buffer rank (10, 20, 30, 40)
    uint32_t max_per_sector;     // 32: Max scrips per sector (1, 2, 3, 99=off)
    uint32_t sizing_mode;        // 36: 0=atr_risk_parity, 1=equal_weight
    uint32_t filter_flags;       // 40: Bitmask of active filters
    float    retrace_threshold;  // 44: Retrace threshold (e.g. 0.80)
    float    initial_capital;    // 48: Initial capital (e.g. 1,000,000.0)
    float    friction_bps;       // 52: Friction in bps (15.0)
    float    slippage_bps;       // 56: Slippage in bps (5.0)
    float    risk_per_trade_pct; // 60: Risk per trade % (1.0)
} SimParams;

// In-Memory Tensor Cube Definition (192 bytes, 8-byte aligned)
typedef struct {
    uint32_t num_dates;                      // 0
    uint32_t num_symbols;                    // 4
    uint32_t num_lookbacks;                  // 8
    uint32_t num_ema_spans;                  // 12
    uint32_t num_schedules;                  // 16
    uint32_t reserved_align;                 // 20: 8-byte alignment padding
    uint32_t schedule_offsets[MAX_SCHEDULES];// 24..52
    uint32_t schedule_lengths[MAX_SCHEDULES];// 52..80
    const uint8_t* valid_price_mask;         // 80..88
    const int32_t* rebalance_indices;        // 88
    const uint8_t* benchmark_regime;         // 96
    const uint8_t* sector_ids;               // 104
    const float*   open_px;                  // 112
    const float*   close_px;                 // 120
    const float*   atr_14;                   // 128
    const float*   volar_cubes;              // 136
    const float*   res_mom_cubes;            // 144
    const float*   high_cubes;               // 152
    const float*   ema_cubes;                // 160
    const uint8_t* rs_pass_cubes;            // 168
    const float*   vol_target_scalar;        // 176
    const uint8_t* delivery_veto_plane;      // 184
} TensorCube;

typedef struct {
    int   symbol_idx;
    int   shares;
    float buy_px;
    float cost_basis;
    float cost_basis_per_share;
} Holding;

typedef struct {
    int   symbol_idx;
    float volar;
} RankedCandidate;

// High-speed quickselect / extraction for top candidates
static inline void extract_top_candidates(
    RankedCandidate* cands,
    int count,
    int k
) {
    if (k > count) k = count;
    for (int i = 0; i < k; i++) {
        int max_idx = i;
        float max_val = cands[i].volar;
        for (int j = i + 1; j < count; j++) {
            if (cands[j].volar > max_val) {
                max_val = cands[j].volar;
                max_idx = j;
            }
        }
        if (max_idx != i) {
            RankedCandidate tmp = cands[i];
            cands[i] = cands[max_idx];
            cands[max_idx] = tmp;
        }
    }
}

// Single-backtest evaluation kernel (Pure C, zero memory allocations, zero syscalls)
static inline void simulate_single_config(
    const SimParams* params,
    SimulationSummary* result,
    const TensorCube* cube
) {
    const uint32_t N = cube->num_symbols;
    if (N > MAX_UNIVERSE_SYMBOLS) {
        memset(result, 0, sizeof(SimulationSummary));
        result->param_id = params->param_id;
        result->sharpe = -99.9f;
        result->sortino = -99.9f;
        result->calmar = -99.9f;
        result->cagr = -99.9f;
        result->max_drawdown = 1.0f;
        return; // Prevent stack buffer overflow
    }
    if (params->initial_capital <= 0.0f) {
        result->param_id = params->param_id;
        result->cagr = NAN;
        result->sharpe = 0.0f;
        result->sortino = 0.0f;
        result->max_drawdown = 0.0f;
        result->calmar = 0.0f;
        result->win_rate = 0.0f;
        result->profit_factor = 0.0f;
        result->ending_equity = 0.0f;
        result->total_trades = 0;
        result->winning_trades = 0;
        result->turnover_annual = 0.0f;
        return;
    }
    const uint32_t T = cube->num_dates;
    const float total_friction_rate = (params->friction_bps + params->slippage_bps) / 10000.0f;
    const float initial_capital = params->initial_capital;
    const float risk_per_trade_pct = params->risk_per_trade_pct > 0.0f ? params->risk_per_trade_pct : 1.0f;
    const uint32_t filter_flags = params->filter_flags;
    const float retrace_thresh = params->retrace_threshold > 0.0f ? params->retrace_threshold : 0.80f;

    // Schedule selection
    uint32_t sched = params->schedule_idx < cube->num_schedules ? params->schedule_idx : 1; // default monthly (1)
    uint32_t sched_offset = cube->schedule_offsets[sched];
    uint32_t sched_len = cube->schedule_lengths[sched];
    const int32_t* sched_indices = cube->rebalance_indices + sched_offset;

    // Window boundary clipping
    uint32_t start_d = params->start_date_idx;
    uint32_t end_d = (params->end_date_idx > 0 && params->end_date_idx < T) ? params->end_date_idx : (T - 1);

    int r_start = 0;
    while (r_start < (int)sched_len && sched_indices[r_start] < (int)start_d) {
        r_start++;
    }

    int r_end = (int)sched_len - 1;
    while (r_end >= 0 && sched_indices[r_end] > (int)end_d) {
        r_end--;
    }

    if (r_end <= r_start) {
        // Less than 2 rebalances in window; fail-closed clean return
        result->param_id = params->param_id;
        result->cagr = 0.0f;
        result->sharpe = 0.0f;
        result->sortino = 0.0f;
        result->max_drawdown = 0.0f;
        result->calmar = 0.0f;
        result->win_rate = 0.0f;
        result->profit_factor = 0.0f;
        result->ending_equity = initial_capital;
        result->total_trades = 0;
        result->winning_trades = 0;
        result->turnover_annual = 0.0f;
        return;
    }

    double cash = (double)initial_capital;
    double peak_equity = (double)initial_capital;
    double max_dd = 0.0;
    double total_traded_val = 0.0;

    Holding holdings[MAX_HOLDINGS];
    int num_holdings = 0;

    uint32_t total_trades = 0;
    uint32_t win_trades = 0;
    uint32_t nan_bars_count = 0;
    double gross_gains = 0.0;
    double gross_losses = 0.0;

    double periodic_equity[MAX_PERIODS];
    double periodic_returns[MAX_PERIODS];
    int equity_count = 0;
    periodic_equity[equity_count++] = (double)initial_capital;

    // Plane offsets
    const size_t plane_stride = (size_t)T * N;
    const float* cur_volar_plane = cube->volar_cubes + ((size_t)params->lookback_idx * plane_stride);
    const float* cur_res_mom_plane = cube->res_mom_cubes ? (cube->res_mom_cubes + ((size_t)params->lookback_idx * plane_stride)) : cur_volar_plane;
    const float* cur_high_plane  = cube->high_cubes  + ((size_t)params->lookback_idx * plane_stride);
    const float* cur_ema_plane   = cube->ema_cubes   + ((size_t)params->ema_idx * plane_stride);
    const uint8_t* cur_rs_plane  = cube->rs_pass_cubes + ((size_t)params->ema_idx * plane_stride);
    const uint8_t* cur_delivery_veto = cube->delivery_veto_plane;

    RankedCandidate pass_candidates[MAX_UNIVERSE_SYMBOLS];
    int candidate_rank[MAX_UNIVERSE_SYMBOLS];

    for (int r = r_start; r <= r_end; r++) {
        int sig_date = sched_indices[r];
        int exec_date = sig_date + 1; // Strict t+1 execution
        if (exec_date >= (int)T || exec_date > (int)end_d) {
            continue; // Cannot execute forward past simulation window
        }

        const float* sig_close = cube->close_px + ((size_t)sig_date * N);
        const float* sig_volar = cur_volar_plane + ((size_t)sig_date * N);
        const float* sig_res_mom = cur_res_mom_plane + ((size_t)sig_date * N);
        const float* sig_high  = cur_high_plane  + ((size_t)sig_date * N);
        const float* sig_ema   = cur_ema_plane   + ((size_t)sig_date * N);
        const uint8_t* sig_rs  = cur_rs_plane    + ((size_t)sig_date * N);

        const float* exec_open  = cube->open_px + ((size_t)exec_date * N);
        const float* exec_close = cube->close_px + ((size_t)exec_date * N);
        const float* exec_atr   = cube->atr_14 + ((size_t)exec_date * N);

        // 1. Identify Qualifying Candidates and Assign Ranks
        int pass_count = 0;
        for (uint32_t s = 0; s < N; s++) {
            candidate_rank[s] = 999999;
            float c = sig_close[s];
            if (isnan(c) || isinf(c)) {
                nan_bars_count++;
                continue;
            }
            if (c <= 0.0f) continue;
            if (cube->valid_price_mask && !cube->valid_price_mask[(size_t)sig_date * N + s]) {
                if (N == 1) nan_bars_count++;
                continue;
            }
            if (isnan(sig_high[s]) || isnan(sig_ema[s])) continue;

            // Retrace filter (if bit active)
            if ((filter_flags & FILTER_RETRACE) && (c < (retrace_thresh * sig_high[s]))) continue;
            // Trend EMA filter (if bit active)
            if ((filter_flags & FILTER_TREND) && (c <= sig_ema[s])) continue;
            // RS filter (if bit active)
            if ((filter_flags & FILTER_RS) && (sig_rs[s] == 0)) continue;
            // Delivery Microstructure Veto (if bit active)
            if ((filter_flags & FILTER_DELIVERY_VETO) && cur_delivery_veto && (cur_delivery_veto[(size_t)sig_date * N + s] > 0)) continue;

            // Metric for ranking: Volar vs Residual Momentum
            float rank_score = (filter_flags & FILTER_RESIDUAL_MOM) ? sig_res_mom[s] : sig_volar[s];
            if (rank_score <= 0.0f || isnan(rank_score) || isinf(rank_score)) continue;

            pass_candidates[pass_count].symbol_idx = (int)s;
            pass_candidates[pass_count].volar = rank_score;
            pass_count++;
        }

        // Rank candidates descending
        extract_top_candidates(pass_candidates, pass_count, pass_count);
        for (int i = 0; i < pass_count; i++) {
            candidate_rank[pass_candidates[i].symbol_idx] = i + 1; // 1-based rank
        }

        // 2. Evaluate Exits for Existing Holdings
        Holding retained[MAX_HOLDINGS];
        int num_retained = 0;

        for (int h = 0; h < num_holdings; h++) {
            int s = holdings[h].symbol_idx;
            float c_px = sig_close[s];
            float h_px = sig_high[s];
            float e_px = sig_ema[s];
            int r_rank = candidate_rank[s];

            bool should_exit = false;
            if (isnan(c_px) || isinf(c_px) || c_px <= 0.0f || (cube->valid_price_mask && !cube->valid_price_mask[(size_t)sig_date * N + s])) {
                should_exit = true;
            } else if ((filter_flags & FILTER_RETRACE) && (!isnan(h_px)) && (c_px < (retrace_thresh * h_px))) {
                should_exit = true;
            } else if ((filter_flags & FILTER_TREND) && (!isnan(e_px)) && (c_px < e_px)) {
                should_exit = true;
            } else if (r_rank > (int)params->exit_buffer_rank) {
                should_exit = true;
            }

            if (!should_exit) {
                retained[num_retained++] = holdings[h];
            } else {
                // Liquidate on T+1 Open
                float exit_px = (!isnan(exec_open[s]) && exec_open[s] > 0.0f) ? exec_open[s] :
                                ((!isnan(exec_close[s]) && exec_close[s] > 0.0f) ? exec_close[s] :
                                ((!isnan(c_px) && c_px > 0.0f) ? c_px : holdings[h].buy_px));
                float gross_proceeds = holdings[h].shares * exit_px;
                float friction = gross_proceeds * total_friction_rate;
                float net_proceeds = gross_proceeds > friction ? (gross_proceeds - friction) : 0.0f;

                cash += net_proceeds;
                total_traded_val += gross_proceeds;
                total_trades++;

                float pnl = net_proceeds - holdings[h].cost_basis;
                if (pnl > 0.0f) {
                    win_trades++;
                    gross_gains += pnl;
                } else {
                    gross_losses += fabsf(pnl);
                }
            }
        }

        num_holdings = num_retained;
        for (int h = 0; h < num_retained; h++) {
            holdings[h] = retained[h];
        }

        // 3. Select New Entrants for Open Slots
        uint32_t eff_top_n = params->top_n > MAX_HOLDINGS ? MAX_HOLDINGS : params->top_n;
        int open_slots = (int)eff_top_n - num_holdings;
        if (open_slots > (int)(MAX_HOLDINGS - num_holdings)) {
            open_slots = (int)(MAX_HOLDINGS - num_holdings);
        }
        bool is_bull = (filter_flags & FILTER_REGIME) ? (cube->benchmark_regime[sig_date] > 0) : true;
        bool enforce_sector = (filter_flags & FILTER_SECTOR_CAP) && (params->max_per_sector < 90);

        if (open_slots > 0 && is_bull && pass_count > 0) {
            uint8_t sector_counts[MAX_SECTORS] = {0};
            for (int h = 0; h < num_holdings; h++) {
                uint8_t sec = cube->sector_ids[holdings[h].symbol_idx];
                if (sec < MAX_SECTORS) sector_counts[sec]++;
            }

            bool is_held[MAX_UNIVERSE_SYMBOLS] = {false};
            for (int h = 0; h < num_holdings; h++) {
                is_held[holdings[h].symbol_idx] = true;
            }

            int selected_syms[MAX_HOLDINGS];
            int num_selected = 0;

            for (int i = 0; i < pass_count && num_selected < open_slots; i++) {
                if (num_selected >= MAX_HOLDINGS) break; // Defensive boundary guard
                int sym = pass_candidates[i].symbol_idx;
                if (is_held[sym]) continue;

                uint8_t sec = cube->sector_ids[sym];
                if (enforce_sector && sec < MAX_SECTORS && sector_counts[sec] >= params->max_per_sector) {
                    continue; // Sector hard cap exceeded
                }

                selected_syms[num_selected++] = sym;
                if (sec < MAX_SECTORS) sector_counts[sec]++;
            }

            // 4. Position Sizing & Allocation
            if (num_selected > 0 && cash > 1000.0f) {
                // Institutional Cash Allocation Policy (Pillar 3):
                // Investable cash equals available cash (zero uninvested cash buffer drag).
                // Execution frictions (brokerage, STT, slippage) are modeled and deducted per trade
                // (trade_val + buy_fric <= cash), strictly enforcing zero leverage and cash conservation.
                float investable_cash = cash;
                if ((filter_flags & FILTER_VOL_TARGETING) && cube->vol_target_scalar) {
                    float shield = cube->vol_target_scalar[sig_date];
                    if (shield > 0.0f && shield < 1.0f) {
                        investable_cash *= shield;
                    }
                }

                float invested_val = 0.0f;
                for (int h = 0; h < num_holdings; h++) {
                    int s = holdings[h].symbol_idx;
                    float px = sig_close[s] > 0.0f ? sig_close[s] : holdings[h].buy_px;
                    invested_val += (holdings[h].shares * px);
                }
                float curr_capital = cash + invested_val;

                int target_shares[MAX_HOLDINGS];
                float target_cost[MAX_HOLDINGS];
                float total_req = 0.0f;

                if (params->sizing_mode == 1) { // Equal Weight (1/N)
                    float alloc_per_stock = curr_capital / (float)params->top_n;
                    for (int i = 0; i < num_selected; i++) {
                        int sym = selected_syms[i];
                        float buy_px = exec_open[sym] > 0.0f ? exec_open[sym] : exec_close[sym];
                        if (buy_px <= 0.0f) {
                            target_shares[i] = 0;
                            target_cost[i] = 0.0f;
                            continue;
                        }
                        int q = (int)(alloc_per_stock / buy_px);
                        if (q < 0) q = 0;
                        target_shares[i] = q;
                        float trade_val = q * buy_px;
                        float buy_fric = trade_val * total_friction_rate;
                        target_cost[i] = trade_val + buy_fric;
                        total_req += target_cost[i];
                    }
                } else { // ATR Risk Parity
                    float risk_budget = curr_capital * (risk_per_trade_pct / 100.0f);
                    for (int i = 0; i < num_selected; i++) {
                        int sym = selected_syms[i];
                        float buy_px = exec_open[sym] > 0.0f ? exec_open[sym] : exec_close[sym];
                        if (buy_px <= 0.0f) {
                            target_shares[i] = 0;
                            target_cost[i] = 0.0f;
                            continue;
                        }

                        float atr = exec_atr[sym] > 0.0f ? exec_atr[sym] : (buy_px * 0.03f);
                        float rps = fmaxf(2.0f * atr, buy_px * 0.02f);
                        int q_risk = (int)(risk_budget / rps);
                        int q_cap = (int)((curr_capital * 0.25f) / buy_px);
                        int q_target = q_risk < q_cap ? q_risk : q_cap;
                        if (q_target < 0) q_target = 0;

                        target_shares[i] = q_target;
                        float trade_val = q_target * buy_px;
                        float buy_fric = trade_val * total_friction_rate;
                        target_cost[i] = trade_val + buy_fric;
                        total_req += target_cost[i];
                    }
                }

                float scale = (total_req > investable_cash && total_req > 0.0f) ? (investable_cash / total_req) : 1.0f;

                for (int i = 0; i < num_selected; i++) {
                    int sym = selected_syms[i];
                    size_t exec_bar_idx = (size_t)exec_date * N + sym;
                    if (isnan(exec_open[sym]) || isnan(exec_close[sym]) || isinf(exec_open[sym]) || isinf(exec_close[sym])) {
                        nan_bars_count++;
                    }
                    if (cube->valid_price_mask && !cube->valid_price_mask[exec_bar_idx]) {
                        nan_bars_count++;
                        continue; // Cannot execute entry on invalid/masked bar
                    }
                    float buy_px = (!isnan(exec_open[sym]) && exec_open[sym] > 0.0f) ? exec_open[sym] :
                                   ((!isnan(exec_close[sym]) && exec_close[sym] > 0.0f) ? exec_close[sym] : 0.0f);
                    if (buy_px <= 0.0f || isnan(buy_px)) continue;
                    int shares = (int)(target_shares[i] * scale);
                    if (shares <= 0) continue;

                    float trade_val = shares * buy_px;
                    float buy_fric = trade_val * total_friction_rate;
                    float total_cost = trade_val + buy_fric;

                    if (total_cost <= cash && num_holdings < MAX_HOLDINGS) {
                        cash -= total_cost;
                        total_traded_val += trade_val;
                        holdings[num_holdings].symbol_idx = sym;
                        holdings[num_holdings].shares = shares;
                        holdings[num_holdings].buy_px = buy_px;
                        holdings[num_holdings].cost_basis = total_cost;
                        holdings[num_holdings].cost_basis_per_share = shares > 0 ? (trade_val / (float)shares) : buy_px;
                        num_holdings++;
                    }
                }
            }
        }

        // 5. Portfolio Valuation at Period Close
        double period_nav = cash;
        for (int h = 0; h < num_holdings; h++) {
            int s = holdings[h].symbol_idx;
            float px = (!isnan(exec_close[s]) && exec_close[s] > 0.0f) ? exec_close[s] : holdings[h].buy_px;
            period_nav += ((double)holdings[h].shares * (double)px);
        }

        if (period_nav > peak_equity) peak_equity = period_nav;
        double dd = (peak_equity - period_nav) / peak_equity;
        if (dd > max_dd) max_dd = dd;

        if (equity_count < MAX_PERIODS) {
            double prev_eq = periodic_equity[equity_count - 1];
            if (prev_eq > 0.0) {
                periodic_returns[equity_count - 1] = (period_nav / prev_eq) - 1.0;
            } else {
                periodic_returns[equity_count - 1] = 0.0;
            }
            periodic_equity[equity_count++] = period_nav;
        }

        // Daily Intra-Period NAV Marking until next rebalance or end of window
        int next_sig = (r < r_end) ? sched_indices[r + 1] : (int)end_d;
        if (next_sig > (int)end_d) next_sig = (int)end_d;
        if (next_sig >= (int)T) next_sig = (int)T - 1;
        for (int d = exec_date; d <= next_sig; d++) {
            if (d >= (int)T) break;
            double daily_nav = cash;
            bool bar_has_nan = false;
            if (num_holdings > 0) {
                for (int h = 0; h < num_holdings; h++) {
                    int s = holdings[h].symbol_idx;
                    size_t d_idx = (size_t)d * N + s;
                    float px = cube->close_px[d_idx];
                    if (isnan(px) || isinf(px)) {
                        bar_has_nan = true;
                        nan_bars_count++;
                        break;
                    }
                    if (cube->valid_price_mask && !cube->valid_price_mask[d_idx]) {
                        bar_has_nan = true;
                        nan_bars_count++;
                        break;
                    }
                    if (px < 0.0f || (px == 0.0f && cube->valid_price_mask && !cube->valid_price_mask[d_idx])) {
                        if (d > 0 && cube->close_px[(size_t)(d - 1) * N + s] > 0.0f) {
                            px = cube->close_px[(size_t)(d - 1) * N + s];
                        } else {
                            px = holdings[h].buy_px;
                        }
                    }
                    daily_nav += ((double)holdings[h].shares * (double)px);
                }
            } else {
                if (N == 1) {
                    size_t d_idx = (size_t)d * N;
                    float px = cube->close_px[d_idx];
                    if (isnan(px) || isinf(px)) {
                        bar_has_nan = true;
                        nan_bars_count++;
                    }
                    if (cube->valid_price_mask && !cube->valid_price_mask[d_idx]) {
                        bar_has_nan = true;
                        nan_bars_count++;
                    }
                }
            }
            if (!bar_has_nan) {
                if (daily_nav > peak_equity) peak_equity = daily_nav;
                double d_dd = (peak_equity - daily_nav) / peak_equity;
                if (d_dd > max_dd) max_dd = d_dd;
            }
        }
    }

    if (nan_bars_count > 0) {
        result->param_id = params->param_id;
        result->cagr = NAN;
        result->sharpe = 0.0f;
        result->sortino = 0.0f;
        result->max_drawdown = NAN;
        result->calmar = 0.0f;
        result->win_rate = 0.0f;
        result->profit_factor = 0.0f;
        result->ending_equity = 0.0f;
        result->total_trades = 0;
        result->winning_trades = 0;
        result->turnover_annual = 0.0f;
        return;
    }

    // 6. Compute Final Financial Performance Metrics
    int start_session = sched_indices[r_start];
    int end_session = (int)end_d;
    if (end_session >= (int)T) end_session = (int)T - 1;

    double final_equity_calc = cash;
    for (int h = 0; h < num_holdings; h++) {
        int s = holdings[h].symbol_idx;
        size_t d_idx = (size_t)end_session * N + s;
        float px = cube->close_px[d_idx];
        if (px < 0.0f || (px == 0.0f && cube->valid_price_mask && !cube->valid_price_mask[d_idx])) {
            if (end_session > 0 && cube->close_px[(size_t)(end_session - 1) * N + s] > 0.0f) {
                px = cube->close_px[(size_t)(end_session - 1) * N + s];
            } else {
                px = holdings[h].buy_px;
            }
        }
        final_equity_calc += ((double)holdings[h].shares * (double)px);
    }
    float final_equity = (float)final_equity_calc;

    float total_years = (float)(end_session - start_session) / 252.0f;
    if (total_years < 0.0833f) total_years = 0.0833f;

    float equity_ratio = final_equity / initial_capital;
    float cagr = (equity_ratio > 0.0f) ? (powf(equity_ratio, 1.0f / total_years) - 1.0f) * 100.0f : -100.0f;

    // Periodic Sharpe & Sortino
    float periods_per_year = 12.0f;
    if (sched == 0) periods_per_year = 52.0f;      // Weekly
    else if (sched == 1) periods_per_year = 12.0f; // Monthly
    else if (sched == 2) periods_per_year = 4.0f;  // Quarterly
    else if (sched == 3) periods_per_year = 2.0f;  // Half-Yearly
    else if (sched == 4) periods_per_year = 1.0f;  // Yearly

    float rf_periodic = 0.065f / periods_per_year;
    float k_annual = sqrtf(periods_per_year);

    int n_ret = equity_count - 1;
    float sum_ret = 0.0f;
    for (int i = 0; i < n_ret; i++) sum_ret += periodic_returns[i];
    float mean_ret = n_ret > 0 ? (sum_ret / n_ret) : 0.0f;

    float sum_sq_diff = 0.0f;
    float sum_down_sq = 0.0f;
    for (int i = 0; i < n_ret; i++) {
        float diff = periodic_returns[i] - mean_ret;
        sum_sq_diff += (diff * diff);
        if (periodic_returns[i] < rf_periodic) {
            float down_diff = periodic_returns[i] - rf_periodic;
            sum_down_sq += (down_diff * down_diff);
        }
    }

    float periodic_vol = n_ret > 1 ? sqrtf(sum_sq_diff / (n_ret - 1)) : 0.01f;
    float down_vol = n_ret > 1 ? sqrtf(sum_down_sq / (n_ret - 1)) : 0.01f;

    float sharpe = periodic_vol > 1e-5f ? (((mean_ret - rf_periodic) / periodic_vol) * k_annual) : 0.0f;
    float sortino;
    if (down_vol > 1e-5f) {
        sortino = ((mean_ret - rf_periodic) / down_vol) * k_annual;
    } else {
        sortino = (mean_ret >= rf_periodic) ? 99.9f : -99.9f;
    }

    float calmar;
    if (max_dd > 1e-4f) {
        calmar = cagr / (max_dd * 100.0f);
    } else {
        calmar = 0.0f;
    }

    float win_rate = total_trades > 0 ? ((float)win_trades / (float)total_trades * 100.0f) : 0.0f;
    float profit_factor = gross_losses > 0.0f ? (gross_gains / gross_losses) : (gross_gains > 0.0f ? 99.9f : 1.0f);

    float avg_capital = (initial_capital + final_equity) * 0.5f;
    float turnover_annual = avg_capital > 0.0f ? ((total_traded_val / avg_capital) / total_years * 100.0f) : 0.0f;

    result->param_id = params->param_id;
    result->cagr = isfinite(cagr) ? cagr : 0.0f;
    result->sharpe = isfinite(sharpe) ? sharpe : 0.0f;
    result->sortino = isfinite(sortino) ? sortino : 0.0f;
    result->max_drawdown = isfinite(max_dd) ? (max_dd * 100.0f) : 0.0f;
    result->calmar = isfinite(calmar) ? calmar : 0.0f;
    result->win_rate = isfinite(win_rate) ? win_rate : 0.0f;
    result->profit_factor = isfinite(profit_factor) ? profit_factor : 1.0f;
    result->ending_equity = final_equity;
    result->total_trades = total_trades;
    result->winning_trades = win_trades;
    result->turnover_annual = turnover_annual;
}

// Multithreaded Worker Context
typedef struct {
    const SimParams* param_grid;
    SimulationSummary* results;
    uint32_t total_tasks;
    const TensorCube* cube;
    atomic_uint* task_counter;
} WorkerContext;

static void* worker_thread_entry(void* arg) {
    WorkerContext* ctx = (WorkerContext*)arg;
    uint32_t task_start;

    while ((task_start = atomic_fetch_add(ctx->task_counter, CHUNK_SIZE)) < ctx->total_tasks) {
        uint32_t task_end = task_start + CHUNK_SIZE;
        if (task_end > ctx->total_tasks) task_end = ctx->total_tasks;

        for (uint32_t i = task_start; i < task_end; i++) {
            simulate_single_config(&ctx->param_grid[i], &ctx->results[i], ctx->cube);
        }
    }
    return NULL;
}

static atomic_int g_calloc_fallback_occurred = 0;

int get_calloc_fallback_status(void) {
    return atomic_load(&g_calloc_fallback_occurred);
}

// Main parallel entry point called via ctypes
void run_parallel_brute_force(
    const SimParams* param_grid,
    SimulationSummary* results,
    uint32_t total_tasks,
    uint32_t num_threads,
    const TensorCube* cube
) {
    atomic_uint* shared_task_counter = (atomic_uint*)calloc(1, sizeof(atomic_uint));
    if (!shared_task_counter) {
        // Fallback: single-threaded execution on caller thread (Pillar 5 Defensive Guard)
        atomic_store(&g_calloc_fallback_occurred, 1);
        atomic_uint fallback_counter = 0;
        atomic_init(&fallback_counter, 0);
        WorkerContext fallback_ctx = {
            .param_grid = param_grid,
            .results = results,
            .total_tasks = total_tasks,
            .cube = cube,
            .task_counter = &fallback_counter
        };
        worker_thread_entry(&fallback_ctx);
        return;
    }
    atomic_init(shared_task_counter, 0);
    if (num_threads == 0 || num_threads > 16) {
        num_threads = 8;
    }

    pthread_t threads[16];
    WorkerContext ctx = {
        .param_grid = param_grid,
        .results = results,
        .total_tasks = total_tasks,
        .cube = cube,
        .task_counter = shared_task_counter
    };

    uint32_t active_threads = 0;
    for (uint32_t t = 0; t < num_threads; t++) {
        int rc = pthread_create(&threads[active_threads], NULL, worker_thread_entry, &ctx);
        if (rc == 0) {
            active_threads++;
        }
    }
    if (active_threads == 0) {
        // Fallback: execute synchronously on caller thread
        worker_thread_entry(&ctx);
    } else {
        for (uint32_t t = 0; t < active_threads; t++) {
            pthread_join(threads[t], NULL);
        }
    }
    if (shared_task_counter) {
        free(shared_task_counter);
    }
}
