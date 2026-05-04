/**
 * @module pos_cod/app/patches/navbar_patch
 *
 * Registers CodBanner as a sub-component of Navbar so the XML template
 * extension can reference it by name.
 */

import { Navbar } from "@point_of_sale/app/navbar/navbar";
import { CodBanner } from "@pos_cod/app/components/cod_banner/CodBanner";

Navbar.components = { ...Navbar.components, CodBanner };
