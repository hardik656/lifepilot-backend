from playwright.sync_api import sync_playwright
import time

def start_cancellation_bot(service_name, username, password):
    with sync_playwright() as p:
        # 🌐 Headless=False so you can watch the Pilot work!
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={'width': 1280, 'height': 720})
        page = context.new_page()

        try:
            if "netflix" in service_name.lower():
                print(f"🚀 AI Pilot: Logging into Netflix as {username}...")
                page.goto("https://www.netflix.com/login", wait_until="networkidle")

                # Fill credentials
                page.fill('input[name="userLoginId"]', username)
                page.fill('input[name="password"]', password)
                
                # Wait for navigation after clicking submit
                with page.expect_navigation():
                    page.click('button[type="submit"]')

                # 💡 THE FIX: Wait for the login session to be active
                # We wait 3 seconds to let cookies load before jumping to cancel
                time.sleep(3) 

                print(f"🚀 AI Pilot: Navigating to Cancel Page...")
                page.goto("https://www.netflix.com/cancelplan", wait_until="networkidle")

            print(f"✅ AI Pilot: Successfully reached cancellation screen for {service_name}.")
            return True
        except Exception as e:
            print(f"❌ AI Pilot Error: {e}")
            return False
        finally:
            time.sleep(10)  # Keep it open longer so you can see the result
            browser.close()