import httpx
import pytest
import respx

from conftest import BASE_URL, articulos_reales
from scrapper_dpec.cliente import ClienteDPEC, ErrorFuenteDPEC

LISTA = f"{BASE_URL}/es/seccion/17-articulos.json"


@respx.mock
def test_lista_real_se_interpreta(cliente: ClienteDPEC) -> None:
    ruta = respx.get(LISTA).mock(return_value=httpx.Response(200, json=articulos_reales()))
    articulos = cliente.listar_recientes()
    assert len(articulos) == 15
    assert articulos[0].articulo_id == 8871
    assert articulos[0].publicado_en.utcoffset().total_seconds() == -3 * 3600
    assert articulos[0].es_corte_publicado
    assert articulos[0].datos_crudos["cantidadVisitas"] > 0
    assert ruta.calls[0].request.url.params["rows"] == "50"
    assert "cookie" not in ruta.calls[0].request.headers  # Funciona sin sesión.


@respx.mock
def test_error_500_se_reintenta(cliente: ClienteDPEC) -> None:
    ruta = respx.get(LISTA).mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json=articulos_reales())]
    )
    assert cliente.listar_recientes()
    assert ruta.call_count == 2


@respx.mock
def test_error_de_conexion_agota_reintentos(cliente: ClienteDPEC) -> None:
    ruta = respx.get(LISTA).mock(side_effect=httpx.ConnectTimeout("lento"))
    with pytest.raises(ErrorFuenteDPEC, match="ConnectTimeout"):
        cliente.listar_recientes()
    assert ruta.call_count == 3


@respx.mock
def test_404_no_se_reintenta(cliente: ClienteDPEC) -> None:
    ruta = respx.get(LISTA).mock(return_value=httpx.Response(404))
    with pytest.raises(ErrorFuenteDPEC, match="404"):
        cliente.listar_recientes()
    assert ruta.call_count == 1


@pytest.mark.parametrize(
    "respuesta",
    [
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"error": "algo"}),
        httpx.Response(200, text="<html>mantenimiento</html>"),
        httpx.Response(200, json=[{"articuloId": "1"}]),
        httpx.Response(200, json=[{**articulos_reales()[0], "enlace": "https://evil.test/x"}]),
        httpx.Response(200, json=[{**articulos_reales()[0], "enlace": "//evil.test/x"}]),
    ],
    ids=["vacia", "objeto", "html", "campos-faltantes", "enlace-externo", "enlace-protocolo"],
)
@respx.mock
def test_formato_inesperado_es_un_error(cliente: ClienteDPEC, respuesta: httpx.Response) -> None:
    respx.get(LISTA).mock(return_value=respuesta)
    with pytest.raises(ErrorFuenteDPEC):
        cliente.listar_recientes()
