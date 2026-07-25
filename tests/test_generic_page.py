from flru.parsers import parse_generic_page


def test_generic_page() -> None:
    page = parse_generic_page(
        """
        <html><head><title>Page</title><meta name='description' content='Desc'>
        <script type='application/ld+json'>{"@type":"Thing"}</script></head>
        <body><main><h1>Hello</h1><p>World</p><ul><li>One</li></ul>
        <table><tr><th>A</th></tr><tr><td>B</td></tr></table>
        <a href='/x'>Link</a><img src='/a.png' alt='A'></main></body></html>
        """,
        "https://www.fl.ru/page/",
    )
    assert page.title == "Page"
    assert page.metadata["description"] == "Desc"
    assert page.headings[0].text == "Hello"
    assert page.tables[0].rows == [["B"]]
    assert page.links[0].url == "https://www.fl.ru/x"
    assert page.images[0].url == "https://www.fl.ru/a.png"
    assert page.json_ld[0]["@type"] == "Thing"
