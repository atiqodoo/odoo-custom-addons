/** @odoo-module **/

import { Component, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { Many2XAutocomplete } from "@web/views/fields/relational_utils";

const COST_PRIORITY_SEQUENCE = ["", "cost_incl_vat_asc", "cost_incl_vat_desc"];
const COST_PRIORITY_LABELS = {
    cost_incl_vat_asc: _t("Cost incl VAT: low to high"),
    cost_incl_vat_desc: _t("Cost incl VAT: high to low"),
};
const COST_PRIORITY_ICONS = {
    cost_incl_vat_asc: "fa-sort-amount-asc",
    cost_incl_vat_desc: "fa-sort-amount-desc",
};

export class ModernQuotationWorkspace extends Component {
    static template = "modern_quotation_catalogue.Workspace";
    static components = { Many2XAutocomplete };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        const context = this.props.action?.context || {};
        this.state = useState({
            loading: true,
            searching: false,
            order: false,
            partners: [],
            pricelists: [],
            warehouses: [],
            categories: [],
            uoms: [],
            attributes: [],
            products: [],
            viewMode: "list",
            total: 0,
            offset: 0,
            limit: 60,
            catalogueSort: "",
            can_view_cost: false,
            has_colour_master: false,
            has_tinting: false,
            selectedPartnerId: false,
            selectedPartnerName: "",
            selectedPricelistId: false,
            selectedWarehouseId: false,
            filters: {
                search: "",
                category_filter: "",
                category_id: false,
                uom_id: false,
                variant_filter: "",
                colour_code: "",
                attribute_value_ids: [],
                quantity: 1,
            },
            comparison: {
                open: false,
                loading: false,
                sortBy: "cost_incl_vat_asc",
                selectedProduct: false,
                targetLine: false,
                basis: false,
                filterOptions: {
                    uoms: [],
                    colourAttributeGroups: [],
                },
                filters: {
                    categoryFilter: "",
                    uomId: false,
                    colourAttributeGroupId: false,
                    colourAttributeFilter: "",
                },
                rows: [],
            },
        });
        this.initialOrderId = context.default_order_id || context.active_id || false;
        this.searchDebounce = null;
        this.comparisonDebounce = null;
        onWillStart(async () => {
            await this.loadBootstrap();
            await this.searchCatalogue();
        });
        onWillUnmount(() => {
            if (this.searchDebounce) {
                clearTimeout(this.searchDebounce);
            }
            if (this.comparisonDebounce) {
                clearTimeout(this.comparisonDebounce);
            }
        });
    }

    async loadBootstrap() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "modern.quotation.catalogue.service",
                "get_bootstrap",
                [this.initialOrderId]
            );
            Object.assign(this.state, data);
            if (data.order) {
                this.applyOrderContext(data.order);
            } else {
                this.state.selectedWarehouseId = data.warehouses[0]?.id || false;
                this.state.selectedPricelistId = data.pricelists[0]?.id || false;
            }
        } finally {
            this.state.loading = false;
        }
    }

    applyOrderContext(order) {
        this.state.order = order;
        this.state.selectedPartnerId = order.partner_id || this.state.selectedPartnerId;
        this.state.selectedPartnerName = order.partner_name || this.state.selectedPartnerName;
        this.state.selectedPricelistId = order.pricelist_id || this.state.selectedPricelistId;
        this.state.selectedWarehouseId = order.warehouse_id || this.state.selectedWarehouseId;
    }

    get catalogueFilters() {
        return {
            ...this.state.filters,
            partner_id: this.state.selectedPartnerId || false,
            pricelist_id: this.state.selectedPricelistId || false,
            warehouse_id: this.state.selectedWarehouseId || false,
            sort_by: this.hasActiveCatalogueFilter ? this.state.catalogueSort : "",
            offset: this.state.offset,
            limit: this.state.limit,
        };
    }

    get hasActiveCatalogueFilter() {
        const filters = this.state.filters;
        return Boolean(
            (filters.search || "").trim() ||
            filters.category_filter ||
            filters.category_id ||
            filters.uom_id ||
            (filters.variant_filter || "").trim() ||
            (filters.colour_code || "").trim() ||
            filters.attribute_value_ids.length
        );
    }

    get costPriorityTitle() {
        if (!this.hasActiveCatalogueFilter) {
            return _t("Apply a catalogue filter first");
        }
        return COST_PRIORITY_LABELS[this.state.catalogueSort] || _t("Variant priority by cost");
    }

    get costPriorityIcon() {
        return COST_PRIORITY_ICONS[this.state.catalogueSort] || "fa-sort";
    }

    get costPriorityButtonClass() {
        return this.hasActiveCatalogueFilter && this.state.catalogueSort ? "btn btn-primary" : "btn btn-secondary";
    }

    async searchCatalogue(reset = false) {
        if (reset) {
            this.state.offset = 0;
        }
        this.state.searching = true;
        try {
            const result = await this.orm.call(
                "modern.quotation.catalogue.service",
                "search_catalogue",
                [this.catalogueFilters]
            );
            this.state.products = result.products;
            this.state.total = result.total;
            this.state.offset = result.offset;
            this.state.limit = result.limit;
        } finally {
            this.state.searching = false;
        }
    }

    scheduleCatalogueSearch() {
        if (this.searchDebounce) {
            clearTimeout(this.searchDebounce);
        }
        this.searchDebounce = setTimeout(() => {
            this.searchDebounce = null;
            this.searchCatalogue(true);
        }, 300);
    }

    async resetCatalogueFilters() {
        if (this.searchDebounce) {
            clearTimeout(this.searchDebounce);
            this.searchDebounce = null;
        }
        Object.assign(this.state.filters, {
            search: "",
            category_filter: "",
            category_id: false,
            uom_id: false,
            variant_filter: "",
            colour_code: "",
            attribute_value_ids: [],
            quantity: 1,
        });
        this.state.catalogueSort = "";
        this.state.offset = 0;
        this.state.viewMode = "list";
        await this.searchCatalogue(true);
    }

    async createQuotation() {
        try {
            const order = await this.orm.call(
                "modern.quotation.catalogue.service",
                "create_or_load_quotation",
                [{
                    partner_id: this.state.selectedPartnerId || false,
                    pricelist_id: this.state.selectedPricelistId || false,
                    warehouse_id: this.state.selectedWarehouseId || false,
                }]
            );
            this.applyOrderContext(order);
            this.notification.add(_t("Quotation created"), { type: "success" });
            return order;
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Could not create quotation")), { type: "danger" });
            return false;
        }
    }

    async addProduct(product) {
        if (!this.state.order) {
            const order = await this.createQuotation();
            if (!order) {
                return;
            }
        }
        if (!this.state.order) {
            return;
        }
        try {
            const order = await this.orm.call(
                "modern.quotation.catalogue.service",
                "add_product_to_quotation",
                [this.state.order.id, product.id, this.state.filters.quantity || 1]
            );
            this.applyOrderContext(order);
            this.notification.add(_t("Product added"), { type: "success" });
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Could not add product")), { type: "danger" });
        }
    }

    onProductKeydown(ev, product) {
        if (!["Enter", " "].includes(ev.key)) {
            return;
        }
        ev.preventDefault();
        this.addProduct(product);
    }

    async updateLineQuantity(line, ev) {
        const quantity = Number(ev.target.value || 0);
        const order = await this.orm.call(
            "modern.quotation.catalogue.service",
            "update_line_quantity",
            [line.id, quantity]
        );
        this.applyOrderContext(order);
    }

    async updateLinePrice(line, ev) {
        const price = Number(ev.target.value || 0);
        const order = await this.orm.call(
            "modern.quotation.catalogue.service",
            "update_line_price",
            [line.id, price]
        );
        this.applyOrderContext(order);
    }

    async removeLine(line) {
        const order = await this.orm.call(
            "modern.quotation.catalogue.service",
            "remove_line",
            [line.id]
        );
        this.applyOrderContext(order);
    }

    async confirmQuotation() {
        if (!this.state.order) {
            return;
        }
        try {
            const order = await this.orm.call(
                "modern.quotation.catalogue.service",
                "confirm_quotation",
                [this.state.order.id]
            );
            this.applyOrderContext(order);
            this.notification.add(_t("Quotation confirmed"), { type: "success" });
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Confirmation blocked")), { type: "danger" });
        }
    }

    async openQuotation() {
        if (!this.state.order) {
            return;
        }
        try {
            const action = await this.orm.call(
                "modern.quotation.catalogue.service",
                "open_quotation_action",
                [this.state.order.id]
            );
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Open blocked")), { type: "danger" });
        }
    }

    async compareQuotationLine(ev, line) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        if (!this.state.order || !line) {
            return;
        }
        if (this.isQuotationLineBelowCost(line)) {
            this.notification.add(_t("Cannot compare: selected line price is below cost incl VAT."), { type: "danger" });
            return;
        }
        const isNewTarget = this.state.comparison.targetLine?.id !== line.id;
        this.state.comparison.open = true;
        this.state.comparison.loading = true;
        if (isNewTarget) {
            Object.assign(this.state.comparison.filters, {
                categoryFilter: "",
                uomId: false,
                colourAttributeGroupId: false,
                colourAttributeFilter: "",
            });
        }
        this.state.comparison.targetLine = line;
        this.state.comparison.selectedProduct = {
            id: line.product_id,
            name: line.name,
        };
        try {
            const result = await this.orm.call(
                "modern.quotation.catalogue.service",
                "compare_similar_variants",
                [
                    line.product_id,
                    this.state.order.id,
                    line.id,
                    line.quantity || 1,
                    this.state.comparison.sortBy,
                    this.catalogueFilters,
                    {
                        category_filter: this.state.comparison.filters.categoryFilter || false,
                        uom_id: this.state.comparison.filters.uomId || false,
                        colour_attribute_group_id: this.state.comparison.filters.colourAttributeGroupId || false,
                        colour_attribute_filter: this.state.comparison.filters.colourAttributeFilter || "",
                    },
                ]
            );
            this.state.comparison.selectedProduct = result.selected_product;
            this.state.comparison.basis = result.basis;
            this.state.comparison.filterOptions.uoms = result.filter_options?.uoms || [];
            this.state.comparison.filterOptions.colourAttributeGroups = result.filter_options?.colour_attribute_groups || [];
            this.state.comparison.filters.categoryFilter = String(result.basis.category_filter || this.state.comparison.filters.categoryFilter || "");
            this.state.comparison.filters.uomId = String(result.basis.uom_id || "");
            this.state.comparison.filters.colourAttributeGroupId = this.state.comparison.filters.colourAttributeGroupId === "all"
                ? "all"
                : String(result.basis.colour_attribute_group_id || "");
            this.state.comparison.rows = this.prepareComparisonRows(result.rows);
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Comparison blocked")), { type: "danger" });
            this.closeVariantComparison();
        } finally {
            this.state.comparison.loading = false;
        }
    }

    prepareComparisonRows(rows) {
        return rows.map((row) => ({
            ...row,
            editable_price_incl_vat: row.sale_price_incl_vat,
            editable_quantity: row.quantity,
        }));
    }

    recomputeComparisonRow(row) {
        const price = Math.max(Number(row.editable_price_incl_vat || 0), 0);
        const quantity = Math.max(Number(row.editable_quantity || 0), 0);
        const lineTotal = price * quantity;
        const lineProfit = lineTotal - (Number(row.cost_incl_vat || 0) * quantity);
        row.quantity = quantity;
        row.sale_price_incl_vat = price;
        row.line_total_if_used = lineTotal;
        row.line_profit_if_used = lineProfit;
        row.current_quote_total = Number(this.state.comparison.basis?.current_quote_total || row.current_quote_total || 0);
        row.quotation_total_if_used = Number(this.state.comparison.basis?.base_total || 0) + lineTotal;
        row.quotation_profit_if_used = Number(this.state.comparison.basis?.base_profit || 0) + lineProfit;
        const replacementLine = row.temporary_quote_lines?.find((line) => line.role === "replacement");
        if (replacementLine) {
            replacementLine.quantity = quantity;
            replacementLine.total = lineTotal;
        }
    }

    onComparisonPriceInput(row, ev) {
        row.editable_price_incl_vat = ev.target.value;
        this.recomputeComparisonRow(row);
    }

    onComparisonQuantityInput(row, ev) {
        row.editable_quantity = ev.target.value;
        this.recomputeComparisonRow(row);
    }

    isQuotationLineBelowCost(line) {
        const quantity = Number(line.quantity || 0);
        const sellingUnitIncl = quantity ? Number(line.total || 0) / quantity : Number(line.price_unit || 0);
        return sellingUnitIncl < Number(line.cost_incl_vat || 0);
    }

    isComparisonRowBelowCost(row) {
        return Number(row.sale_price_incl_vat || 0) < Number(row.cost_incl_vat || 0);
    }

    notifyAlternateBelowCost(row) {
        this.notification.add(
            _t("Cannot apply alternate: selling price is below cost incl VAT."),
            { type: "danger" }
        );
    }

    async replaceWithAlternate(row) {
        if (!this.state.comparison.targetLine) {
            return;
        }
        this.recomputeComparisonRow(row);
        if (this.isComparisonRowBelowCost(row)) {
            this.notifyAlternateBelowCost(row);
            return;
        }
        try {
            const order = await this.orm.call(
                "modern.quotation.catalogue.service",
                "replace_line_with_alternate",
                [
                    this.state.comparison.targetLine.id,
                    row.id,
                    row.quantity || row.editable_quantity || this.state.comparison.basis?.quantity || 1,
                    row.sale_price_incl_vat,
                ]
            );
            this.applyOrderContext(order);
            this.closeVariantComparison();
            this.notification.add(_t("Alternate replaced selected line"), { type: "success" });
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Alternate replacement blocked")), { type: "danger" });
        }
    }

    async addAlternateAsNewLine(row) {
        if (!this.state.order) {
            return;
        }
        this.recomputeComparisonRow(row);
        if (this.isComparisonRowBelowCost(row)) {
            this.notifyAlternateBelowCost(row);
            return;
        }
        try {
            const order = await this.orm.call(
                "modern.quotation.catalogue.service",
                "add_alternate_to_quotation",
                [
                    this.state.order.id,
                    row.id,
                    row.quantity || row.editable_quantity || this.state.comparison.basis?.quantity || 1,
                    row.sale_price_incl_vat,
                ]
            );
            this.applyOrderContext(order);
            this.notification.add(_t("Alternate added to quotation"), { type: "success" });
        } catch (error) {
            this.notification.add(this.getErrorMessage(error, _t("Alternate add blocked")), { type: "danger" });
        }
    }

    async onSelectComparisonUom(ev) {
        this.state.comparison.filters.uomId = ev.target.value || false;
        if (this.state.comparison.targetLine) {
            await this.compareQuotationLine(null, this.state.comparison.targetLine);
        }
    }

    async onSelectComparisonCategory(ev) {
        this.state.comparison.filters.categoryFilter = ev.target.value || "";
        if (this.state.comparison.targetLine) {
            await this.compareQuotationLine(null, this.state.comparison.targetLine);
        }
    }

    onComparisonColourFilterInput(ev) {
        this.state.comparison.filters.colourAttributeFilter = ev.target.value || "";
        this.state.comparison.filters.colourAttributeGroupId = false;
        if (this.comparisonDebounce) {
            clearTimeout(this.comparisonDebounce);
        }
        this.comparisonDebounce = setTimeout(async () => {
            this.comparisonDebounce = null;
            if (this.state.comparison.targetLine) {
                await this.compareQuotationLine(null, this.state.comparison.targetLine);
            }
        }, 300);
    }

    async toggleComparisonSort() {
        this.state.comparison.sortBy = this.state.comparison.sortBy === "cost_incl_vat_asc"
            ? "cost_incl_vat_desc"
            : "cost_incl_vat_asc";
        if (this.state.comparison.targetLine) {
            await this.compareQuotationLine(null, this.state.comparison.targetLine);
        }
    }

    closeVariantComparison() {
        Object.assign(this.state.comparison, {
            open: false,
            loading: false,
            selectedProduct: false,
            targetLine: false,
            basis: false,
            filterOptions: {
                uoms: [],
                colourAttributeGroups: [],
            },
            filters: {
                categoryFilter: "",
                uomId: false,
                colourAttributeGroupId: false,
                colourAttributeFilter: "",
            },
            rows: [],
        });
    }

    async nextPage() {
        if (this.state.offset + this.state.limit >= this.state.total) {
            return;
        }
        this.state.offset += this.state.limit;
        await this.searchCatalogue();
    }

    async previousPage() {
        this.state.offset = Math.max(this.state.offset - this.state.limit, 0);
        await this.searchCatalogue();
    }

    onSearchInput(ev) {
        this.state.filters.search = ev.target.value;
        this.scheduleCatalogueSearch();
    }

    onSelectPartner(ev) {
        this.state.selectedPartnerId = this.parseSelection(ev.target.value);
        const partner = this.state.partners.find((item) => item.id === this.state.selectedPartnerId);
        this.state.selectedPartnerName = partner?.name || "";
    }

    onPartnerAutocompleteUpdate(records) {
        const record = Array.isArray(records) ? records[0] : records;
        this.state.selectedPartnerId = record?.id || false;
        this.state.selectedPartnerName = record?.display_name || record?.name || "";
        this.searchCatalogue(true);
    }

    async quickCreatePartner(name) {
        const record = await this.orm.call(
            "modern.quotation.catalogue.service",
            "quick_create_customer",
            [name]
        );
        this.onPartnerAutocompleteUpdate([record]);
    }

    onSelectPricelist(ev) {
        this.state.selectedPricelistId = this.parseSelection(ev.target.value);
        this.searchCatalogue(true);
    }

    onSelectWarehouse(ev) {
        this.state.selectedWarehouseId = this.parseSelection(ev.target.value);
        this.searchCatalogue(true);
    }

    onSelectCategory(ev) {
        const value = ev.target.value || "";
        this.state.filters.category_filter = value;
        this.state.filters.category_id = value && !value.includes(":") ? this.parseSelection(value) : false;
        this.searchCatalogue(true);
    }

    onSelectUom(ev) {
        this.state.filters.uom_id = this.parseSelection(ev.target.value);
        this.searchCatalogue(true);
    }

    onVariantFilterInput(ev) {
        const value = ev.target.value || "";
        this.state.filters.variant_filter = value;
        this.state.filters.colour_code = value;
        this.scheduleCatalogueSearch();
    }

    onQuantityInput(ev) {
        this.state.filters.quantity = Math.max(Number(ev.target.value || 1), 0.01);
    }

    setViewMode(mode) {
        this.state.viewMode = mode;
    }

    async toggleCostPrioritySort() {
        if (!this.hasActiveCatalogueFilter) {
            return;
        }
        const currentIndex = COST_PRIORITY_SEQUENCE.indexOf(this.state.catalogueSort);
        const nextIndex = currentIndex >= 0 ? currentIndex + 1 : 1;
        this.state.catalogueSort = COST_PRIORITY_SEQUENCE[nextIndex % COST_PRIORITY_SEQUENCE.length];
        await this.searchCatalogue(true);
    }

    toggleAttributeValue(valueId) {
        const values = this.state.filters.attribute_value_ids;
        const index = values.indexOf(valueId);
        if (index >= 0) {
            values.splice(index, 1);
        } else {
            values.push(valueId);
        }
        this.searchCatalogue(true);
    }

    parseSelection(value) {
        return value ? Number(value) : false;
    }

    getErrorMessage(error, fallback) {
        return error?.data?.message || error?.message || fallback;
    }
}

registry.category("actions").add("modern_quotation_catalogue.workspace", ModernQuotationWorkspace);
