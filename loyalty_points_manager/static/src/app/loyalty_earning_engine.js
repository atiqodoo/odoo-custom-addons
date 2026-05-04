/** @odoo-module **/

/**
 * loyalty_earning_engine.js
 *
 * Pure, stateless utility functions for POS loyalty points calculation.
 * NO side effects — every function is deterministic and independently testable.
 *
 * Load order dependency: this file must be listed BEFORE the patch files
 * in the manifest's point_of_sale._assets_pos bundle.
 *
 * Server mirror: models/pos_order_override.py (_compute_net_earning_base_server,
 * _distribute_proportionally).  Any logic change here must be reflected there.
 *
 * Algorithm overview
 * ──────────────────
 *  1. classifyOrderLines()    — tag each product line as UNIT_RULE or VALUE_RULE
 *  2. distributeProportionally() — allocate a deduction pool across lines (LRM)
 *  3. computeNetLineValues()  — run two proportional passes (discount, redemption)
 *  4. calculateTotalPointsToEarn() — apply rule rates to net values / quantities
 */

// ─────────────────────────────────────────────────────────────────────────────
// 1. LINE CLASSIFICATION
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Classify every non-reward product line into a rule bucket.
 *
 * Priority rule: if a product matches a UNIT rule it is excluded from any
 * VALUE rule pool to prevent double-earning.
 *
 * @param {Object[]} orderlines   - Orderline model instances from the POS Order
 * @param {Object[]} loyaltyRules - loyalty.rule records loaded in the POS session
 * @returns {{
 *   unitRuleLines: {line, rule}[],
 *   valueRuleLines: {line, rule}[],
 *   nonEarningLines: {line}[]
 * }}
 */
export function classifyOrderLines(orderlines, loyaltyRules) {
    const unitRuleLines = [];
    const valueRuleLines = [];
    const nonEarningLines = [];

    for (const line of orderlines) {
        // Reward/discount lines are deductions, never earners
        if (line.is_reward_line) continue;

        const unitRule = _findUnitRule(line, loyaltyRules);
        if (unitRule) {
            unitRuleLines.push({ line, rule: unitRule });
            continue;
        }

        const valueRule = _findValueRule(line, loyaltyRules);
        if (valueRule) {
            valueRuleLines.push({ line, rule: valueRule });
        } else {
            nonEarningLines.push({ line });
        }
    }

    return { unitRuleLines, valueRuleLines, nonEarningLines };
}

/**
 * Find a unit-based rule (reward_point_mode === 'unit_paid') for this line.
 * @private
 */
function _findUnitRule(line, rules) {
    return rules.find(
        (r) => r.reward_point_mode === 'unit' && _ruleMatchesProduct(r, line.product_id)
    ) || null;
}

/**
 * Find a value-based rule (reward_point_mode === 'money') for this line.
 * A rule with no product restriction applies to every product.
 * @private
 */
function _findValueRule(line, rules) {
    return rules.find((r) => {
        if (r.reward_point_mode !== 'money') return false;
        if (!r.product_ids?.length && !r.product_category_id) return true;
        return _ruleMatchesProduct(r, line.product_id);
    }) || null;
}

/**
 * Check whether a loyalty rule applies to a specific product.
 * @private
 */
function _ruleMatchesProduct(rule, product) {
    if (!product) return false;
    if (rule.product_ids?.length) {
        return rule.product_ids.includes(product.id);
    }
    if (rule.product_category_id) {
        // product.pos_category_ids covers POS categories; categ_id covers internal category
        return (
            product.pos_category_ids?.includes(rule.product_category_id) ||
            product.categ_id?.id === rule.product_category_id
        );
    }
    return true; // no product restriction → matches all
}

// ─────────────────────────────────────────────────────────────────────────────
// 2. PROPORTIONAL DISTRIBUTION  (Largest Remainder Method)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Allocate `pool` across `lineValues` entries in proportion to their values.
 *
 * Uses the Largest Remainder Method so that the sum of all allocated shares
 * equals `pool` exactly — no floating-point drift, no missing/extra cents.
 *
 * @param {{ id: string|number, value: number }[]} lineValues
 * @param {number} pool  - total deduction amount to distribute
 * @returns {Object}     - { [line.id]: allocatedShare }
 */
export function distributeProportionally(lineValues, pool) {
    const result = {};

    if (pool <= 0) {
        for (const lv of lineValues) result[lv.id] = 0;
        return result;
    }

    const total = lineValues.reduce((s, lv) => s + lv.value, 0);
    if (total <= 0) {
        for (const lv of lineValues) result[lv.id] = 0;
        return result;
    }

    const fractionals = [];
    let totalFloored = 0;

    for (const lv of lineValues) {
        const exact = (lv.value / total) * pool;
        const floored = Math.floor(exact * 100) / 100;
        result[lv.id] = floored;
        totalFloored += floored;
        fractionals.push({ id: lv.id, frac: exact - floored });
    }

    // Give residual penny-increments to lines with the largest fractional parts
    let residual = Math.round((pool - totalFloored) * 100) / 100;
    fractionals.sort((a, b) => b.frac - a.frac);

    for (const { id } of fractionals) {
        if (residual <= 0) break;
        const bump = Math.min(0.01, residual);
        result[id] = Math.round((result[id] + bump) * 100) / 100;
        residual = Math.round((residual - bump) * 100) / 100;
    }

    return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// 3. NET LINE VALUE COMPUTATION  (two-pass deduction)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Return the tax-inclusive net paid value for each product line after:
 *   Pass 1 — global discount reward lines allocated proportionally
 *   Pass 2 — other redemption reward lines allocated proportionally
 *             (using post-discount weights for Pass 2, not original weights)
 *
 * @param {Object[]} allOrderlines  - All lines on the order (including reward lines)
 * @param {Object[]} loyaltyRules   - loyalty.rule records from POS session
 * @returns {{
 *   netValues: Object,                     // { line.cid: net_paid_value }
 *   classified: ReturnType<classifyOrderLines>
 * }}
 */
export function computeNetLineValues(allOrderlines, loyaltyRules) {
    const productLines = allOrderlines.filter((l) => !l.is_reward_line);
    const rewardLines  = allOrderlines.filter((l) => l.is_reward_line);

    // ── Build gross values (tax-inclusive, after line-level discounts) ──────
    const grossEntries = productLines.map((line) => ({
        id: line.cid,
        value: Math.max(0, _getTaxInclusiveTotal(line)),
    }));

    // ── Pass 1: distribute global discount ───────────────────────────────────
    const globalDiscountAmount = rewardLines
        .filter((l) => l.reward?.reward_type === 'discount')
        .reduce((s, l) => s + Math.abs(_getTaxInclusiveTotal(l)), 0);

    const discountAlloc = distributeProportionally(grossEntries, globalDiscountAmount);

    const postDiscountEntries = grossEntries.map((gv) => ({
        id: gv.id,
        value: Math.max(0, gv.value - (discountAlloc[gv.id] || 0)),
    }));

    // ── Pass 2: distribute redemption pool ───────────────────────────────────
    const redemptionAmount = rewardLines
        .filter((l) => l.reward?.reward_type !== 'discount')
        .reduce((s, l) => s + Math.abs(_getTaxInclusiveTotal(l)), 0);

    const redemptionAlloc = distributeProportionally(postDiscountEntries, redemptionAmount);

    // ── Final net values ─────────────────────────────────────────────────────
    const netValues = {};
    for (const pdv of postDiscountEntries) {
        netValues[pdv.id] = Math.max(0, pdv.value - (redemptionAlloc[pdv.id] || 0));
    }

    const classified = classifyOrderLines(productLines, loyaltyRules);
    return { netValues, classified };
}

/**
 * Get the tax-inclusive total for a single order line.
 * Tries the method first (Odoo 18 model API), then falls back to the
 * computed property (Odoo 17-style).
 * @private
 */
function _getTaxInclusiveTotal(line) {
    if (typeof line.get_price_with_tax === 'function') {
        return line.get_price_with_tax();
    }
    return line.price_subtotal_incl ?? 0;
}

// ─────────────────────────────────────────────────────────────────────────────
// 4. POINTS ACCUMULATION
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Compute the total loyalty points the customer earns for this order after
 * all discounts and redemptions have been deducted.
 *
 * UNIT_RULE lines  → points = qty × rule.reward_point_amount
 *                    (discount-immune: only physical quantity matters)
 *
 * VALUE_RULE lines → points = floor(net_paid / rule.reward_point_split_amount)
 *                              × rule.reward_point_amount
 *                    (discount-sensitive: uses the net paid value)
 *
 * @param {Object[]} allOrderlines - All lines including reward lines
 * @param {Object[]} loyaltyRules  - loyalty.rule records from POS session
 * @returns {number} Total whole-number points to earn
 */
export function calculateTotalPointsToEarn(allOrderlines, loyaltyRules) {
    if (!allOrderlines?.length || !loyaltyRules?.length) return 0;

    const { netValues, classified } = computeNetLineValues(allOrderlines, loyaltyRules);
    let totalPoints = 0;

    // ── Unit-rule lines: quantity drives the calculation ─────────────────────
    for (const { line, rule } of classified.unitRuleLines) {
        const qty = typeof line.get_quantity === 'function'
            ? line.get_quantity()
            : (line.qty ?? 0);
        totalPoints += Math.floor(Math.abs(qty) * (rule.reward_point_amount || 0));
    }

    // ── Value-rule lines: net monetary value drives the calculation ──────────
    for (const { line, rule } of classified.valueRuleLines) {
        const netPaid = netValues[line.cid] || 0;
        const splitAmount = rule.reward_point_split_amount || 100; // KES per point tier
        if (splitAmount > 0) {
            totalPoints += Math.floor(netPaid / splitAmount) * (rule.reward_point_amount || 1);
        }
    }

    return totalPoints;
}

/**
 * Return the maximum redeemable value for a partner given a reward.
 * Used by the orderline redemption patch to validate edits.
 *
 * @param {number} loyaltyPoints      - Partner's current point balance
 * @param {Object} reward             - loyalty.reward record
 * @returns {number} Maximum KES value redeemable
 */
export function maxRedeemableValue(loyaltyPoints, reward) {
    if (!reward?.discount_per_point || loyaltyPoints <= 0) return 0;
    return loyaltyPoints * reward.discount_per_point;
}
