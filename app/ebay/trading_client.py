"""Trading API (XML) - GetSellerList / GetItem / ReviseItem.

Les annonces creees dans l'UI eBay ne sont pas forcement visibles par
l'Inventory API tant qu'elles n'ont pas ete migrees : on passe par la Trading
API historique, authentifiee avec le token OAuth via l'en-tete X-EBAY-API-IAF-TOKEN
(pas de <RequesterCredentials> XML necessaire avec un token OAuth).

Doc: https://developer.ebay.com/devzone/xml/docs/reference/ebay/GetSellerList.html
     https://developer.ebay.com/devzone/xml/docs/reference/ebay/GetItem.html
     https://developer.ebay.com/devzone/xml/docs/reference/ebay/ReviseItem.html

ReviseItem est prevu mais volontairement non appele en phase 1 (application
des corrections = phase suivante, hors perimetre).
"""

from __future__ import annotations

import datetime as dt
from xml.etree import ElementTree as ET

import httpx

from app.config import Settings, get_settings
from app.ebay.retry import with_ebay_retry

TRADING_ENDPOINT = "/ws/api.dll"
NS = "urn:ebay:apis:eBLBaseComponents"


class TradingApiError(RuntimeError):
    pass


def _headers(call_name: str, access_token: str, settings: Settings) -> dict:
    return {
        "X-EBAY-API-SITEID": str(settings.ebay_trading_site_id),
        "X-EBAY-API-COMPATIBILITY-LEVEL": str(settings.ebay_trading_compatibility_level),
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-IAF-TOKEN": access_token,
        "Content-Type": "text/xml",
    }


@with_ebay_retry
def _post(call_name: str, xml_body: str, access_token: str, settings: Settings) -> ET.Element:
    response = httpx.post(
        f"{settings.ebay_api_base}{TRADING_ENDPOINT}",
        headers=_headers(call_name, access_token, settings),
        content=xml_body.encode("utf-8"),
        timeout=60,
    )
    response.raise_for_status()
    root = ET.fromstring(response.content)
    ack = root.findtext(f"{{{NS}}}Ack")
    if ack not in ("Success", "Warning"):
        errors = [
            e.findtext(f"{{{NS}}}LongMessage")
            for e in root.findall(f"{{{NS}}}Errors")
        ]
        raise TradingApiError(f"{call_name} a echoue (Ack={ack}): {errors}")
    return root


def get_seller_list(access_token: str, settings: Settings | None = None) -> list[dict]:
    """Recupere les annonces actives.

    GetSellerList exige un filtre StartTime* ou EndTime* de moins de 120 jours.
    "Fin dans les 119 prochains jours" couvre les annonces GTC (renouvelees
    chaque mois).
    """
    settings = settings or get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    end_from = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_to = (now + dt.timedelta(days=119)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    items: list[dict] = []
    page_number = 1
    while True:
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetSellerListRequest xmlns="{NS}">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <GranularityLevel>Fine</GranularityLevel>
  <EndTimeFrom>{end_from}</EndTimeFrom>
  <EndTimeTo>{end_to}</EndTimeTo>
  <Pagination>
    <EntriesPerPage>200</EntriesPerPage>
    <PageNumber>{page_number}</PageNumber>
  </Pagination>
</GetSellerListRequest>"""
        root = _post("GetSellerList", xml_body, access_token, settings)
        for item in root.findall(f".//{{{NS}}}Item"):
            price = item.find(f"{{{NS}}}SellingStatus/{{{NS}}}CurrentPrice")
            items.append(
                {
                    "item_id": item.findtext(f"{{{NS}}}ItemID"),
                    "sku": item.findtext(f"{{{NS}}}SKU"),
                    "title": item.findtext(f"{{{NS}}}Title"),
                    "price": price.text if price is not None else None,
                    "currency": price.attrib.get("currencyID") if price is not None else None,
                    "quantity": item.findtext(f"{{{NS}}}Quantity"),
                    "status": item.findtext(f"{{{NS}}}SellingStatus/{{{NS}}}ListingStatus"),
                    "start_time": item.findtext(f"{{{NS}}}ListingDetails/{{{NS}}}StartTime"),
                }
            )
        if root.findtext(f"{{{NS}}}HasMoreItems") != "true":
            return items
        page_number += 1


def get_item(item_id: str, access_token: str, settings: Settings | None = None) -> dict:
    """Detail d'une annonce : titre, item specifics, prix, photos."""
    settings = settings or get_settings()
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{NS}">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
  <IncludeItemSpecifics>true</IncludeItemSpecifics>
</GetItemRequest>"""
    root = _post("GetItem", xml_body, access_token, settings)
    item = root.find(f"{{{NS}}}Item")
    if item is None:
        raise TradingApiError(f"GetItem: item {item_id} introuvable dans la reponse")

    specifics = {}
    for ns_el in item.findall(f"{{{NS}}}ItemSpecifics/{{{NS}}}NameValueList"):
        name = ns_el.findtext(f"{{{NS}}}Name")
        values = [v.text for v in ns_el.findall(f"{{{NS}}}Value")]
        if name:
            specifics[name] = values if len(values) > 1 else (values[0] if values else None)

    photo_urls = [
        u.text
        for u in item.findall(f"{{{NS}}}PictureDetails/{{{NS}}}PictureURL")
        if u.text
    ]

    # Un SKU peut n'exister que sur les variantes : le premier suffit.
    sku_candidates = [item.findtext(f"{{{NS}}}SKU")] + [
        v.findtext(f"{{{NS}}}SKU")
        for v in item.findall(f"{{{NS}}}Variations/{{{NS}}}Variation")
    ]
    sku = next((s.strip() for s in sku_candidates if s and s.strip()), None)

    # Quantity inclut les unites deja vendues.
    quantity = item.findtext(f"{{{NS}}}Quantity")
    if quantity is not None:
        sold = item.findtext(f"{{{NS}}}SellingStatus/{{{NS}}}QuantitySold") or "0"
        quantity = str(max(int(quantity) - int(sold), 0))

    return {
        "item_id": item.findtext(f"{{{NS}}}ItemID"),
        "sku": sku,
        "title": item.findtext(f"{{{NS}}}Title"),
        "item_specifics": specifics,
        "price": item.findtext(f"{{{NS}}}StartPrice"),
        "quantity": quantity,
        "photo_count": len(photo_urls),
    }


def revise_item_title_or_price(
    item_id: str,
    *,
    new_title: str | None = None,
    new_price: str | None = None,
    access_token: str,
    settings: Settings | None = None,
) -> ET.Element:
    """Prevu pour la phase suivante (application des corrections). Non appele en phase 1.

    Le brief impose de ne jamais reviser titre et prix ensemble : applique ici
    au niveau de la signature (un seul des deux peut etre fourni).
    """
    if bool(new_title) == bool(new_price):
        raise ValueError("Fournir new_title OU new_price, jamais les deux ni aucun.")

    settings = settings or get_settings()
    field_xml = (
        f"<Title>{new_title}</Title>" if new_title else f"<StartPrice>{new_price}</StartPrice>"
    )
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{NS}">
  <ErrorLanguage>en_US</ErrorLanguage>
  <WarningLevel>High</WarningLevel>
  <Item>
    <ItemID>{item_id}</ItemID>
    {field_xml}
  </Item>
</ReviseItemRequest>"""
    return _post("ReviseItem", xml_body, access_token, settings)
