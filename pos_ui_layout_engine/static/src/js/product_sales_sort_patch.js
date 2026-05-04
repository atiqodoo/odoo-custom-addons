/** @odoo-module */

import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { patch } from "@web/core/utils/patch";

const PREFIX = "[POS UI Layout Engine][Sales Sort]";

function productSalesScore(product) {
    return Number(
        product?.pos_ui_template_sold_qty ??
        product?.raw?.pos_ui_template_sold_qty ??
        product?._raw?.pos_ui_template_sold_qty ??
        product?.data?.pos_ui_template_sold_qty ??
        product?.pos_ui_sold_qty ??
        product?.raw?.pos_ui_sold_qty ??
        product?._raw?.pos_ui_sold_qty ??
        product?.data?.pos_ui_sold_qty ??
        0
    ) || 0;
}

function productVariantSalesScore(product) {
    return Number(
        product?.pos_ui_sold_qty ??
        product?.raw?.pos_ui_sold_qty ??
        product?._raw?.pos_ui_sold_qty ??
        product?.data?.pos_ui_sold_qty ??
        0
    ) || 0;
}

function productSalesRank(product) {
    return Number(
        product?.pos_ui_template_sales_rank ??
        product?.raw?.pos_ui_template_sales_rank ??
        product?._raw?.pos_ui_template_sales_rank ??
        product?.data?.pos_ui_template_sales_rank ??
        product?.pos_ui_sales_rank ??
        product?.raw?.pos_ui_sales_rank ??
        product?._raw?.pos_ui_sales_rank ??
        product?.data?.pos_ui_sales_rank ??
        0
    ) || 0;
}

function productName(product) {
    return (product?.display_name || product?.name || "").toString();
}

function hasTemplateSalesScore(product) {
    return (
        product?.pos_ui_template_sold_qty !== undefined ||
        product?.raw?.pos_ui_template_sold_qty !== undefined ||
        product?._raw?.pos_ui_template_sold_qty !== undefined ||
        product?.data?.pos_ui_template_sold_qty !== undefined
    );
}

function applySalesPayload(product, payload = {}) {
    for (const [fieldName, value] of Object.entries(payload)) {
        product[fieldName] = value;
        if (product.raw) {
            product.raw[fieldName] = value;
        }
        if (product._raw) {
            product._raw[fieldName] = value;
        }
        if (product.data) {
            product.data[fieldName] = value;
        }
    }
}

function sortBySalesThenName(products) {
    return [...(products || [])].sort((left, right) => {
        const salesDiff = productSalesScore(right) - productSalesScore(left);
        if (salesDiff) {
            return salesDiff;
        }
        return productName(left).localeCompare(productName(right));
    });
}

function summarizeProducts(products) {
    return (products || []).slice(0, 10).map((product) => ({
        id: product.id,
        name: product.display_name || product.name,
        templateSoldQty: productSalesScore(product),
        variantSoldQty: productVariantSalesScore(product),
        rank: productSalesRank(product),
    }));
}

patch(ProductScreen.prototype, {
    setup(...args) {
        super.setup(...args);
        this.posUiSalesRankingInflightIds = new Set();
        this.posUiSalesRankingEnrichedIds = new Set();
        Promise.resolve().then(() => this.posUiEnrichSalesRanking(this.products || []));
    },

    async posUiEnrichSalesRanking(products, options = {}) {
        if (!this.pos?.config?.ui_sort_products_by_sales || !products?.length) {
            return;
        }
        const force = Boolean(options.force);
        const productIds = [];
        for (const product of products) {
            if (
                product?.id &&
                (force || !hasTemplateSalesScore(product)) &&
                !this.posUiSalesRankingInflightIds.has(product.id)
            ) {
                productIds.push(product.id);
            }
        }
        if (!productIds.length) {
            return;
        }

        productIds.forEach((productId) => this.posUiSalesRankingInflightIds.add(productId));
        try {
            const payload = await this.pos.data.call(
                "product.product",
                "get_pos_ui_sales_ranking_for_products",
                [productIds, this.pos.config.id]
            );
            for (const product of products) {
                const salesPayload = payload?.[product.id];
                if (salesPayload) {
                    applySalesPayload(product, salesPayload);
                    this.posUiSalesRankingEnrichedIds.add(product.id);
                }
            }
            console.debug(`${PREFIX} enriched product ranking`, {
                requested: productIds.length,
                returned: Object.keys(payload || {}).length,
                rankingScope: this.pos?.config?.ui_sales_ranking_scope,
                rankingDays: this.pos?.config?.ui_sales_ranking_days,
                top: summarizeProducts(sortBySalesThenName(products)),
            });
            this.render();
        } catch (error) {
            console.error(`${PREFIX} failed to enrich product ranking`, {
                productIds,
                error,
            });
        } finally {
            productIds.forEach((productId) => this.posUiSalesRankingInflightIds.delete(productId));
        }
    },

    posUiQueueSalesRankingEnrichment(products) {
        if (!products?.some((product) => product?.id && !hasTemplateSalesScore(product))) {
            return;
        }
        Promise.resolve().then(() => this.posUiEnrichSalesRanking(products));
    },

    get productsToDisplay() {
        if (!this.pos?.config?.ui_sort_products_by_sales) {
            return super.productsToDisplay || [];
        }

        let list = [];
        if (this.searchWord !== "") {
            if (!this._searchTriggered) {
                this.pos.setSelectedCategory(0);
                this._searchTriggered = true;
            }
            list = this.addMainProductsToDisplay(this.getProductsBySearchWord(this.searchWord));
        } else {
            this._searchTriggered = false;
            list = this.pos.selectedCategory?.id
                ? this.getProductsByCategory(this.pos.selectedCategory)
                : this.products;
        }

        if (!list || list.length === 0) {
            return [];
        }

        this.posUiQueueSalesRankingEnrichment(list);
        const sortedCandidates = sortBySalesThenName(list);
        const excludedProductIds = [
            this.pos.config.tip_product_id?.id,
            ...this.pos.hiddenProductIds,
            ...this.pos.session._pos_special_products_ids,
        ];

        const filteredList = [];
        for (const product of sortedCandidates) {
            if (filteredList.length >= 100) {
                break;
            }
            if (!excludedProductIds.includes(product.id) && product.canBeDisplayed) {
                filteredList.push(product);
            }
        }

        if (filteredList.length && !filteredList.some((product) => productSalesScore(product))) {
            console.warn(`${PREFIX} all visible products have soldQty=0`, {
                searchWord: this.searchWord,
                rankingScope: this.pos?.config?.ui_sales_ranking_scope,
                rankingDays: this.pos?.config?.ui_sales_ranking_days,
                candidateCount: list.length,
                sample: filteredList.slice(0, 10).map((product) => ({
                    id: product.id,
                    name: product.display_name || product.name,
                    raw: product.raw,
                    directTemplateSoldQty: product.pos_ui_template_sold_qty,
                    directVariantSoldQty: product.pos_ui_sold_qty,
                })),
            });
        }
        console.debug(`${PREFIX} sorted products`, {
            searchWord: this.searchWord,
            candidateCount: list.length,
            displayCount: filteredList.length,
            rankingScope: this.pos?.config?.ui_sales_ranking_scope,
            rankingDays: this.pos?.config?.ui_sales_ranking_days,
            topCandidates: summarizeProducts(sortedCandidates),
            topDisplayed: summarizeProducts(filteredList),
        });
        return filteredList;
    },

    addMainProductsToDisplay(products) {
        const displayProducts = super.addMainProductsToDisplay(products);
        if (!this.pos?.config?.ui_sort_products_by_sales) {
            return displayProducts;
        }
        return sortBySalesThenName(displayProducts);
    },

    async loadProductFromDB(...args) {
        const products = await super.loadProductFromDB(...args);
        await this.posUiEnrichSalesRanking(products || [], { force: true });
        return products;
    },
});
