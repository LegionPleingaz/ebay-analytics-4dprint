import httpx
import pytest
import respx

from app.ebay.trading_client import TradingApiError, get_item, get_seller_list

ENDPOINT = "https://api.sandbox.ebay.com/ws/api.dll"

GET_SELLER_LIST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GetSellerListResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <ItemArray>
    <Item>
      <ItemID>110123456789</ItemID>
      <SKU>NFP-001</SKU>
      <Title>Support moteur 3D NFP</Title>
      <Quantity>5</Quantity>
      <SellingStatus>
        <CurrentPrice currencyID="EUR">24.90</CurrentPrice>
        <ListingStatus>Active</ListingStatus>
      </SellingStatus>
      <ListingDetails>
        <StartTime>2026-01-15T10:00:00.000Z</StartTime>
      </ListingDetails>
    </Item>
  </ItemArray>
</GetSellerListResponse>"""

GET_ITEM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Success</Ack>
  <Item>
    <ItemID>110123456789</ItemID>
    <Title>Support moteur 3D NFP</Title>
    <StartPrice>24.90</StartPrice>
    <Quantity>5</Quantity>
    <ItemSpecifics>
      <NameValueList>
        <Name>Marque</Name>
        <Value>NFP</Value>
      </NameValueList>
      <NameValueList>
        <Name>Compatibilite</Name>
        <Value>Modele A</Value>
        <Value>Modele B</Value>
      </NameValueList>
    </ItemSpecifics>
    <PictureDetails>
      <PictureURL>https://example.test/1.jpg</PictureURL>
      <PictureURL>https://example.test/2.jpg</PictureURL>
    </PictureDetails>
  </Item>
</GetItemResponse>"""

GET_ITEM_ERROR_XML = """<?xml version="1.0" encoding="UTF-8"?>
<GetItemResponse xmlns="urn:ebay:apis:eBLBaseComponents">
  <Ack>Failure</Ack>
  <Errors>
    <LongMessage>Item not found</LongMessage>
  </Errors>
</GetItemResponse>"""


@respx.mock
def test_get_seller_list_parses_items(settings):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content=GET_SELLER_LIST_XML))

    items = get_seller_list("token-abc", settings)

    assert len(items) == 1
    assert items[0]["item_id"] == "110123456789"
    assert items[0]["sku"] == "NFP-001"
    assert items[0]["price"] == "24.90"
    assert items[0]["currency"] == "EUR"
    assert items[0]["status"] == "Active"


@respx.mock
def test_get_item_parses_specifics_and_photo_count(settings):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content=GET_ITEM_XML))

    detail = get_item("110123456789", "token-abc", settings)

    assert detail["title"] == "Support moteur 3D NFP"
    assert detail["item_specifics"]["Marque"] == "NFP"
    assert detail["item_specifics"]["Compatibilite"] == ["Modele A", "Modele B"]
    assert detail["photo_count"] == 2


@respx.mock
def test_get_item_raises_on_failure_ack(settings):
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content=GET_ITEM_ERROR_XML))

    with pytest.raises(TradingApiError):
        get_item("999", "token-abc", settings)


@respx.mock
@pytest.mark.parametrize(
    "extra,expected_sku",
    [
        ("<SKU>4DP-ITEM</SKU><Variations><Variation><SKU>4DP-VAR</SKU></Variation></Variations>", "4DP-ITEM"),
        ("<Variations><Variation/><Variation><SKU>4DP-VAR</SKU></Variation></Variations>", "4DP-VAR"),
        ("", None),
    ],
)
def test_get_item_sku_falls_back_to_variations(settings, extra, expected_sku):
    xml = GET_ITEM_XML.replace("<Quantity>5</Quantity>", "<Quantity>5</Quantity>" + extra)
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content=xml.encode()))

    assert get_item("110123456789", "token-abc", settings)["sku"] == expected_sku


@respx.mock
def test_get_item_quantity_excludes_sold_units(settings):
    xml = GET_ITEM_XML.replace(
        "<Quantity>5</Quantity>",
        "<Quantity>5</Quantity><SellingStatus><QuantitySold>3</QuantitySold></SellingStatus>",
    )
    respx.post(ENDPOINT).mock(return_value=httpx.Response(200, content=xml.encode()))

    assert get_item("110123456789", "token-abc", settings)["quantity"] == "2"
