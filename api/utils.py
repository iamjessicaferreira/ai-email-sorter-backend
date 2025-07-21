import asyncio
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

SUCCESS_PATTERNS = [
    "you've been unsubscribed",
    "sorry to see you go",
    "you have been removed",
    "you have been unsubscribed",
    "you are now unsubscribed",
    "unsubscribe successful",
    "successfully unsubscribed",
    "unsubscribed from our email list",
    "we're sorry to see you go",
    "subscription canceled",
    "assinatura cancelada",
    "removido com sucesso",
    "descadastrado",
    "você foi removido",
    "cancelamento realizado",
    "cancelamos sua inscrição",
    "você foi descadastrado",
    "você não receberá mais e-mails",
    "seu e-mail foi removido",
    "sua inscrição foi cancelada",
    "saída da lista confirmada",
]

UNSUBSCRIBE_SELECTORS = [
    'text="Unsubscribe"',
    'text="Cancelar inscrição"',
    'text="Cancelar subscrição"',
    'text="Opt out"',
    'text="Descadastrar"',
    'text="Remover"',
    'button:has-text("Unsubscribe")',
    'button:has-text("Cancelar inscrição")',
    'button:has-text("Remover")',
    'input[value*="Unsubscribe"]',
]

CAPTCHA_PATTERNS = [
    "are you a person or a robot",
    "please complete the captcha",
    "i am not a robot",
    "solve the captcha",
    "robot check",
    "please verify you are human",
    "enable javascript and cookies",
    "cloudflare",
    "prove you are not a robot",
]

ALL_UNSUBSCRIBE_KEYWORDS = [
    "unsubscribe from all", "remove me from all", "stop all emails", "opt out of all",
    "unsubscribe from every", "unsubscribe all", "unsubscribe from everything",
    "cancel all", "remove all", "descadastrar de todos", "parar todos"
]

ALL_BUTTON_SELECTORS = [
    'button', 'input[type="button"]', 'input[type="submit"]', 'a', '[role="button"]'
]

CHECKBOX_SELECTORS = [
    'input[type="checkbox"]', '[role="checkbox"]'
]

SUBMIT_BUTTON_KEYWORDS = [
    "unsubscribe", "save", "update", "submit", "continue", "confirm", "apply", "done", "finish",
    "descadastrar", "remover", "parar", "salvar"
]


def extract_unsubscribe_links(html: str) -> list:
    """
    Extracts all unsubscribe-related links from the provided HTML content.

    Args:
        html (str): The HTML content to parse.

    Returns:
        list: A list of unsubscribe-related URLs found in the HTML.
    """
    soup = BeautifulSoup(html, "html.parser")
    links = []
    for a in soup.find_all("a", href=True):
        text = (a.text or '').lower()
        href = a['href'].lower()
        if ("unsubscribe" in href or "unsubscribe" in text or
            "descadastrar" in href or "descadastrar" in text or
            "optout" in href or "optout" in text or
            "opt-out" in href or "opt-out" in text):
            links.append(a['href'])
    return links


async def _automate_unsubscribe(url: str) -> str:
    """
    Navigates to the given unsubscribe URL and attempts to automate the unsubscribe process.

    The function tries various methods to unsubscribe, including clicking on
    global unsubscribe buttons, checking checkboxes, clicking submit/unsubscribe buttons,
    and submitting forms. It also checks for captcha and success messages.

    Args:
        url (str): The unsubscribe URL to navigate and interact with.

    Returns:
        str: "success" if the process succeeded,
             "captcha" if a captcha was detected,
             or "failure" if no confirmation of success was detected.
    """
    print(f"[UNSUBSCRIBE] Tentando desinscrever do link: {url}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = await context.new_page()
        await page.goto(url, timeout=30000)
        try:
            await page.wait_for_selector('body', timeout=8000)
        except Exception:
            pass
        await asyncio.sleep(2)

        try:
            body_text = await page.evaluate("document.body.innerText")
        except Exception:
            body_text = await page.content()
        page_text_lower = body_text.lower()
        if any(captcha in page_text_lower for captcha in CAPTCHA_PATTERNS):
            print(f"[Unsubscribe] Página de captcha detectada: {url}")
            await browser.close()
            return "captcha"

        if any(success in page_text_lower for success in SUCCESS_PATTERNS):
            print("[Unsubscribe] Mensagem de sucesso detectada ao abrir:", url)
            await browser.close()
            return "success"

        print("iniciou funcao")

        found = False
        for selector in ALL_BUTTON_SELECTORS + CHECKBOX_SELECTORS:
            elements = await page.query_selector_all(selector)
            for el in elements:
                try:
                    el_text = (await el.inner_text()).lower()
                except Exception:
                    el_text = ""
                if any(key in el_text for key in ALL_UNSUBSCRIBE_KEYWORDS):
                    try:
                        tag = await el.evaluate("(e) => e.tagName")
                        if tag and "checkbox" in selector:
                            await el.check()
                        else:
                            await el.click()
                        await asyncio.sleep(1)
                        new_text = (await page.evaluate("document.body.innerText")).lower()
                        if any(success in new_text for success in SUCCESS_PATTERNS):
                            print(f"[Unsubscribe] Encontrou/desmarcou/desinscreveu usando ação global em:", url)
                            await browser.close()
                            return "success"
                        found = True
                        break
                    except Exception as e:
                        print(f"Erro ao clicar em global unsubscribe: {e}")
                        continue
            if found:
                break

        if found:
            await browser.close()
            return "success"

        checkboxes = await page.query_selector_all('input[type="checkbox"]')
        for checkbox in checkboxes:
            try:
                is_checked = await checkbox.is_checked()
                is_disabled = await checkbox.is_disabled()
                if not is_checked and not is_disabled:
                    await checkbox.check()
            except Exception:
                continue

        await asyncio.sleep(1)

        for selector in ALL_BUTTON_SELECTORS:
            buttons = await page.query_selector_all(selector)
            for btn in buttons:
                try:
                    btn_text = (await btn.inner_text()).lower()
                    if any(word in btn_text for word in SUBMIT_BUTTON_KEYWORDS):
                        await btn.click()
                        await asyncio.sleep(2)
                        after_click_text = (await page.evaluate("document.body.innerText")).lower()
                        if any(success in after_click_text for success in SUCCESS_PATTERNS):
                            print(f"[Unsubscribe] Clicou botão submit/unsubscribe e teve sucesso em:", url)
                            await browser.close()
                            return "success"
                except Exception:
                    continue

        forms = await page.query_selector_all("form")
        for form in forms:
            try:
                await form.evaluate("(form) => form.submit()")
                await asyncio.sleep(2)
                body_text3 = await page.evaluate("document.body.innerText")
                if any(success in body_text3.lower() for success in SUCCESS_PATTERNS):
                    print(f"[Unsubscribe] Submeteu formulário e encontrou mensagem de sucesso em:", url)
                    await browser.close()
                    return "success"
            except Exception:
                continue

        print("[Unsubscribe] Nenhuma confirmação de sucesso detectada em:", url)
        await browser.close()
        return "failure"
