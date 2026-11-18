"""UN M49 regions for the countries WFP reports prices for (used for heterogeneity summaries only)."""

from __future__ import annotations

_M49 = {
    "Northern Africa": "DZA EGY LBY SDN MAR TUN",
    "Eastern Africa": "BDI DJI ETH KEN MDG MOZ MWI RWA SOM SSD TZA UGA ZMB ZWE ERI COM MUS",
    "Middle Africa": "AGO CAF CMR COD COG GAB TCD GNQ STP",
    "Southern Africa": "LSO NAM SWZ ZAF BWA",
    "Western Africa": "BEN BFA CIV CPV GHA GIN GMB GNB LBR MLI MRT NER NGA SEN SLE TGO",
    "Latin America and the Caribbean": (
        "ARG BOL BRA CHL COL CRI CUB DOM ECU GTM HND HTI JAM MEX NIC PAN PER PRY SLV URY VEN"
    ),
    "Central Asia": "KAZ KGZ TJK TKM UZB",
    "Eastern Asia": "CHN JPN MNG PRK KOR",
    "South-eastern Asia": "IDN KHM LAO MMR PHL THA TLS VNM MYS",
    "Southern Asia": "AFG BGD BTN IND IRN LKA NPL PAK",
    "Western Asia": "ARM AZE GEO IRQ JOR LBN PSE SYR TUR YEM",
    "Europe": "BLR MDA RUS UKR",
    "Oceania": "FJI PNG SLB VUT",
}
SUBREGION = {c: r for r, cs in _M49.items() for c in cs.split()}


def subregion(iso3: str) -> str:
    return SUBREGION.get(iso3, "Other")


def macro_region(iso3: str) -> str:
    r = subregion(iso3)
    if r.endswith("Africa"):
        return "Africa"
    if r.endswith("Asia"):
        return "Asia"
    if r == "Latin America and the Caribbean":
        return "Americas"
    if r in ("Europe", "Oceania"):
        return "Europe and Oceania"
    return "Other"
