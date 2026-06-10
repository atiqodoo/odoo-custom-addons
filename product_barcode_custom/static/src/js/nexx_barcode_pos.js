/** @odoo-module */
import { patch } from "@web/core/utils/patch";
import { ProductProduct } from "@point_of_sale/app/models/product_product";
import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";

// 1. Include nexx_barcode in the POS local text search string so the search bar finds it.
patch(ProductProduct.prototype, {
    get searchString() {
        const fields = ["display_name", "barcode", "default_code", "nexx_barcode"];
        return fields
            .map((field) => this[field] || "")
            .filter(Boolean)
            .join(" ");
    },
});

patch(ProductScreen.prototype, {
    _findExactProductByBarcode(codeText) {
        if (!codeText) {
            return null;
        }
        return this.pos.models["product.product"].find(
            (p) => (p.barcode && p.barcode === codeText) || (p.nexx_barcode && p.nexx_barcode === codeText)
        );
    },

    _makeBarcodeCode(codeText) {
        return { code: codeText, base_code: codeText };
    },

    async _addExactBarcodeProduct(product, code) {
        await this.pos.addLineToCurrentOrder({ product_id: product }, { code }, false);
        this.pos.searchProductWord = "";
        this.numberBuffer.reset();
    },

    async _loadExactProductFromDBByBarcode(codeText) {
        const products = await this.pos.data.searchRead(
            "product.product",
            [
                "|",
                ["barcode", "=", codeText],
                ["nexx_barcode", "=", codeText],
                ["available_in_pos", "=", true],
                ["sale_ok", "=", true],
            ],
            this.pos.data.fields["product.product"],
            {
                context: { display_default_code: false },
                limit: 1,
            }
        );
        if (!products.length) {
            return null;
        }
        await this.pos.processProductAttributesByProducts(products);
        await this.pos._loadMissingPricelistItems(products);
        return products[0];
    },

    // 2. Check exact variant barcodes in the local product store before Odoo's
    // standard lookup, which can return a configurable display product.
    async _getProductByBarcode(code) {
        const exactProduct = this._findExactProductByBarcode(code.base_code);
        if (exactProduct) {
            return exactProduct;
        }
        const byNexx = this.pos.models["product.product"].find(
            (p) => p.nexx_barcode && p.nexx_barcode === code.base_code
        );
        if (byNexx) {
            return byNexx;
        }
        return (await super._getProductByBarcode(code)) || this._loadExactProductFromDBByBarcode(code.base_code);
    },

    _isExactProductBarcode(product, code) {
        const codeText = code?.base_code || code?.code || "";
        return Boolean(
            product &&
                codeText &&
                (product.barcode === codeText || product.nexx_barcode === codeText)
        );
    },

    // Exact barcode scans identify the concrete product variant already, so
    // do not open the variant/attribute configurator.
    async _barcodeProductAction(code) {
        const exactProduct = this._findExactProductByBarcode(code.base_code);
        const product = exactProduct || (await this._getProductByBarcode(code));

        if (!product) {
            this.sound.play("error");
            this.barcodeReader.showNotFoundNotification(code);
            return;
        }

        if (exactProduct || this._isExactProductBarcode(product, code)) {
            await this._addExactBarcodeProduct(product, code);
        } else {
            await this.pos.addLineToCurrentOrder(
                { product_id: product },
                { code },
                product.needToConfigure()
            );
            this.numberBuffer.reset();
        }
    },

    // 3. Include nexx_barcode in the "Search more" server-side product lookup domain.
    loadProductFromDBDomain(searchProductWord) {
        return [
            "|",
            "|",
            "|",
            ["name", "ilike", searchProductWord],
            ["default_code", "ilike", searchProductWord],
            ["barcode", "ilike", searchProductWord],
            ["nexx_barcode", "ilike", searchProductWord],
            ["available_in_pos", "=", true],
            ["sale_ok", "=", true],
        ];
    },

    // 4. If the scanner types into the POS search box, Enter normally only
    // runs "Search more". Treat exact barcode text as a scan and add it.
    async onPressEnterKey() {
        const codeText = (this.pos.searchProductWord || "").trim();
        if (codeText) {
            const code = this._makeBarcodeCode(codeText);
            const exactProduct = this._findExactProductByBarcode(codeText);
            const product = exactProduct || (await this._getProductByBarcode(code));
            if (product) {
                if (exactProduct || this._isExactProductBarcode(product, code)) {
                    await this._addExactBarcodeProduct(product, code);
                } else {
                    await this.pos.addLineToCurrentOrder(
                        { product_id: product },
                        { code },
                        product.needToConfigure()
                    );
                    this.pos.searchProductWord = "";
                    this.numberBuffer.reset();
                }
                return;
            }
        }
        return super.onPressEnterKey();
    },

    // If a scanner typed into the search box and the user taps the visible
    // product tile, add the exact variant instead of opening attributes.
    async addProductToOrder(product) {
        const codeText = (this.pos.searchProductWord || "").trim();
        const exactProduct = this._findExactProductByBarcode(codeText);
        if (exactProduct) {
            await this._addExactBarcodeProduct(exactProduct, this._makeBarcodeCode(codeText));
            return;
        }
        return super.addProductToOrder(product);
    },
});
