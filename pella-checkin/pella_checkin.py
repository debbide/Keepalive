#!/usr/bin/env python3
"""
Pella 自动续期脚本 (增强版 - 修复登录超时问题)
支持单账号和多账号

新增功能:
- 自动截图调试功能
- 多重元素选择器策略
- 智能等待和重试机制
- 详细的调试日志
- 更安全的 JavaScript 注入

配置变量说明:
- 单账号变量:
    - PELLA_EMAIL / LEAFLOW_EMAIL=登录邮箱
    - PELLA_PASSWORD / LEAFLOW_PASSWORD=登录密码
- 多账号变量:
    - PELLA_ACCOUNTS / LEAFLOW_ACCOUNTS: 格式：邮箱1:密码1,邮箱2:密码2,邮箱3:密码3
- 通知变量 (可选):
    - TG_BOT_TOKEN=Telegram 机器人 Token
    - TG_CHAT_ID=Telegram 聊天 ID
- 调试变量 (可选):
    - DEBUG_MODE=1 启用调试模式（保存截图和页面源码）
"""

import os
import time
import logging
import re
import requests
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class PellaAutoRenew:
    # 配置class类常量
    LOGIN_URL = "https://www.pella.app/login"
    HOME_URL = "https://www.pella.app/home"
    RENEW_WAIT_TIME = 8
    WAIT_TIME_AFTER_LOGIN = 20  # 增加到 20 秒

    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.telegram_bot_token = os.getenv('TG_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TG_CHAT_ID', '')
        self.debug_mode = os.getenv('DEBUG_MODE', '0') == '1'
        self.screenshot_dir = 'screenshots'

        # 存储初始时间的详细信息 (字符串) 和总天数 (浮点数)
        self.initial_expiry_details = "N/A"
        self.initial_expiry_value = -1.0
        self.server_url = None

        if not self.email or not self.password:
            raise ValueError("邮箱和密码不能为空")

        # 创建截图目录
        if self.debug_mode and not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir)

        self.driver = None
        self.setup_driver()

    def setup_driver(self):
        """设置Chrome驱动选项"""
        chrome_options = Options()

        # GitHub Actions环境配置
        if os.getenv('GITHUB_ACTIONS'):
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--window-size=1920,1080')

        # 通用配置
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)

        # 添加更多反检测措施
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

        try:
            self.driver = webdriver.Chrome(options=chrome_options)
            self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        except WebDriverException as e:
            logger.error(f"❌ 驱动初始化失败，请检查 Chrome/WebDriver 版本是否匹配: {e}")
            raise

    def save_debug_info(self, step_name):
        """保存调试信息（截图和页面源码）"""
        if not self.debug_mode:
            return

        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            safe_email = self.email.split('@')[0][:10]

            # 保存截图
            screenshot_path = os.path.join(self.screenshot_dir, f"{safe_email}_{step_name}_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            logger.info(f"📸 截图已保存: {screenshot_path}")

            # 保存页面源码
            html_path = os.path.join(self.screenshot_dir, f"{safe_email}_{step_name}_{timestamp}.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            logger.info(f"💾 页面源码已保存: {html_path}")

        except Exception as e:
            logger.warning(f"⚠️ 保存调试信息失败: {e}")

    def wait_for_element_clickable(self, by, value, timeout=10):
        """等待元素可点击"""
        return WebDriverWait(self.driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )

    def wait_for_element_present(self, by, value, timeout=10):
        """等待元素出现"""
        return WebDriverWait(self.driver, timeout).until(
            EC.presence_of_element_located((by, value))
        )

    def safe_js_set_value(self, element, value):
        """使用 send_keys 模拟真实输入，兼容性更好"""
        try:
            element.clear()
            element.send_keys(value)
        except Exception as e:
            logger.warning(f"⚠️ send_keys 失败，尝试 JS 输入: {e}")
            self.driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input', { bubbles: true }));"
                "arguments[0].dispatchEvent(new Event('change', { bubbles: true }));",
                element, value
            )

    def find_element_with_multiple_selectors(self, selectors, timeout=10):
        """尝试多个选择器查找元素"""
        for selector_type, selector_value in selectors:
            try:
                logger.info(f"🔍 尝试选择器: {selector_type}='{selector_value}'")
                element = WebDriverWait(self.driver, timeout).until(
                    EC.presence_of_element_located((selector_type, selector_value))
                )
                logger.info(f"✅ 找到元素: {selector_type}='{selector_value}'")
                return element
            except TimeoutException:
                logger.warning(f"⚠️ 选择器未找到元素: {selector_type}='{selector_value}'")
                continue
        return None

    def extract_expiry_days(self, page_source):
        """从页面源码中提取过期时间"""
        days_int = 0
        hours_int = 0
        minutes_int = 0
        found = False

        # 格式1: "Your server expires in 14D 5H 30M" (旧格式)
        match = re.search(r"Your server expires in\s*(\d+)D\s*(\d+)H\s*(\d+)M", page_source)
        if match:
            days_int = int(match.group(1))
            hours_int = int(match.group(2))
            minutes_int = int(match.group(3))
            found = True

        # 格式2: "Expires in 30H 3M" (新格式 - 标题区)
        if not found:
            match = re.search(r"Expires in\s*(\d+)H\s*(\d+)M", page_source, re.IGNORECASE)
            if match:
                hours_int = int(match.group(1))
                minutes_int = int(match.group(2))
                found = True

        # 格式3: "Your server is expiring in 20 Hours 3 Minutes" (新格式 - 正文区)
        if not found:
            match = re.search(r"expiring in\s*(\d+)\s*Hours?\s*(\d+)\s*Minutes?", page_source, re.IGNORECASE)
            if match:
                hours_int = int(match.group(1))
                minutes_int = int(match.group(2))
                found = True

        # 格式4: "Expires in 5D 10H 30M" (带天数的新格式)
        if not found:
            match = re.search(r"Expires in\s*(\d+)D\s*(\d+)H\s*(\d+)M", page_source, re.IGNORECASE)
            if match:
                days_int = int(match.group(1))
                hours_int = int(match.group(2))
                minutes_int = int(match.group(3))
                found = True

        # 格式5: 只有天数 "Your server expires in 14D"
        if not found:
            match = re.search(r"(?:expires|expiring) in\s*(\d+)D", page_source, re.IGNORECASE)
            if match:
                days_int = int(match.group(1))
                found = True

        if found:
            # 构建详细字符串
            parts = []
            if days_int > 0:
                parts.append(f"{days_int} 天")
            if hours_int > 0:
                parts.append(f"{hours_int} 小时")
            if minutes_int > 0:
                parts.append(f"{minutes_int} 分钟")
            detailed_string = " ".join(parts) if parts else "0 分钟"

            # 计算总天数（浮点数）
            total_days_float = days_int + (hours_int / 24) + (minutes_int / (24 * 60))
            return detailed_string, total_days_float

        logger.warning("⚠️ 页面中未找到有效的服务器过期时间格式。")
        return "无法提取", -1.0

    def login(self):
        """执行登录流程（增强版）"""
        logger.info(f"🔑 开始登录流程")
        self.driver.get(self.LOGIN_URL)
        time.sleep(3)  # 初始等待页面加载

        self.save_debug_info("step1_initial_page")

        # ========== 步骤 1: 输入邮箱 ==========
        try:
            logger.info("🔍 步骤 1: 查找邮箱输入框...")

            email_selectors = [
                (By.CSS_SELECTOR, "input[name='identifier']"),
                (By.CSS_SELECTOR, "input[type='email']"),
                (By.XPATH, "//input[@name='identifier']"),
                (By.XPATH, "//input[@type='email']"),
            ]

            email_input = self.find_element_with_multiple_selectors(email_selectors, 15)

            if not email_input:
                self.save_debug_info("error_no_email_input")
                raise Exception("❌ 找不到邮箱输入框")

            self.safe_js_set_value(email_input, self.email)
            logger.info("✅ 邮箱输入完成")
            time.sleep(1)

        except Exception as e:
            self.save_debug_info("error_email_input")
            raise Exception(f"❌ 输入邮箱失败: {e}")

        # ========== 步骤 2: 点击第一个 Next/Continue (提交邮箱) ==========
        try:
            logger.info("🔍 步骤 2: 查找并点击 Next/Continue 按钮 (提交邮箱)...")

            continue_btn_selectors = [
                # Next 按钮（Pella 使用的是 Next）
                (By.XPATH, "//button[contains(translate(text(), 'NEXT', 'next'), 'next') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                (By.XPATH, "//button[contains(translate(., 'NEXT', 'next'), 'next') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                # Continue 按钮（备用）
                (By.XPATH, "//button[contains(translate(text(), 'CONTINUE', 'continue'), 'continue') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                (By.XPATH, "//button[contains(translate(., 'CONTINUE', 'continue'), 'continue') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                # 通用提交按钮
                (By.CSS_SELECTOR, "button[type='submit']:not([aria-label*='Google'])"),
                (By.XPATH, "//button[@type='submit' and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
            ]

            continue_btn_1 = self.find_element_with_multiple_selectors(continue_btn_selectors, 10)

            if not continue_btn_1:
                self.save_debug_info("error_no_continue_btn_1")
                raise Exception("❌ 找不到第一个 Next/Continue 按钮")

            initial_url = self.driver.current_url

            # 尝试 JS 点击
            self.driver.execute_script("arguments[0].click();", continue_btn_1)
            logger.info("✅ 已点击 Next/Continue 按钮 (提交邮箱)")

            # 等待 URL 变化或页面状态改变
            try:
                WebDriverWait(self.driver, 10).until(EC.url_changes(initial_url))
                logger.info("✅ 页面已切换")
            except TimeoutException:
                logger.warning("⚠️ URL 未改变，但继续流程...")

            time.sleep(2)
            self.save_debug_info("step2_after_email_submit")

        except Exception as e:
            self.save_debug_info("error_continue_btn_1")
            raise Exception(f"❌ 点击第一个 Continue 按钮失败: {e}")

        # ========== 步骤 3: 输入密码 ==========
        try:
            logger.info("🔍 步骤 3: 查找密码输入框...")

            password_selectors = [
                (By.CSS_SELECTOR, "input[type='password']"),
                (By.CSS_SELECTOR, "input[name='password']"),
                (By.XPATH, "//input[@type='password']"),
                (By.XPATH, "//input[@name='password']"),
            ]

            password_input = self.find_element_with_multiple_selectors(password_selectors, 20)

            if not password_input:
                self.save_debug_info("error_no_password_input")
                raise Exception("❌ 找不到密码输入框")

            self.safe_js_set_value(password_input, self.password)
            logger.info("✅ 密码输入完成")
            time.sleep(2)  # 等待验证

            self.save_debug_info("step3_after_password_input")

        except Exception as e:
            self.save_debug_info("error_password_input")
            raise Exception(f"❌ 输入密码失败: {e}")

        # ========== 步骤 4: 点击最终 Next/Continue (提交登录) ==========
        try:
            logger.info("🔍 步骤 4: 查找最终 Next/Continue 按钮 (提交登录)...")

            # 增加等待时间，确保按钮激活
            time.sleep(5)

            login_btn_selectors = [
                # Next 按钮（优先，Pella 密码页使用 Next）
                (By.XPATH, "//button[contains(translate(text(), 'NEXT', 'next'), 'next') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                (By.XPATH, "//button[contains(translate(., 'NEXT', 'next'), 'next') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                (By.XPATH, "//button[@type='submit' and contains(translate(., 'NEXT', 'next'), 'next') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                # Continue 按钮（备用）
                (By.XPATH, "//button[contains(translate(text(), 'CONTINUE', 'continue'), 'continue') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                (By.XPATH, "//button[contains(translate(., 'CONTINUE', 'continue'), 'continue') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                (By.XPATH, "//button[@type='submit' and contains(translate(., 'CONTINUE', 'continue'), 'continue') and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                # 表单内的提交按钮
                (By.CSS_SELECTOR, "form button[type='submit']:not([aria-label*='Google'])"),
                (By.XPATH, "//form//button[@type='submit' and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                # Clerk 认证系统特定选择器
                (By.XPATH, "//button[contains(@class, 'cl-formButtonPrimary')]"),
                (By.XPATH, "//form//button[contains(@class, 'cl-')]"),
                # 通用提交按钮
                (By.CSS_SELECTOR, "button[type='submit']:not([disabled]):not([aria-label*='Google'])"),
                (By.XPATH, "//button[@type='submit' and not(@disabled) and not(contains(translate(., 'GOOGLE', 'google'), 'google'))]"),
                # 任何可见的提交按钮
                (By.CSS_SELECTOR, "button[type='submit']:not([aria-label*='Google'])"),
            ]

            login_btn = self.find_element_with_multiple_selectors(login_btn_selectors, 25)

            if not login_btn:
                self.save_debug_info("error_no_login_btn")

                # 尝试查找并输出所有可见的按钮
                all_buttons = self.driver.find_elements(By.TAG_NAME, "button")
                logger.info(f"🔍 页面上找到 {len(all_buttons)} 个按钮:")
                for idx, btn in enumerate(all_buttons):
                    try:
                        logger.info(f"  按钮 {idx+1}: text='{btn.text}', visible={btn.is_displayed()}, enabled={btn.is_enabled()}")
                    except:
                        pass

                raise Exception("❌ 找不到最终 Next/Continue 按钮")

            # 智能等待按钮启用
            max_wait_for_enable = 10
            wait_interval = 0.5
            elapsed = 0

            while not login_btn.is_enabled() and elapsed < max_wait_for_enable:
                logger.warning(f"⚠️ 登录按钮当前被禁用，等待中... ({elapsed:.1f}s/{max_wait_for_enable}s)")
                time.sleep(wait_interval)
                elapsed += wait_interval

            if login_btn.is_enabled():
                logger.info("✅ 登录按钮已启用")
            else:
                logger.warning(f"⚠️ 登录按钮仍被禁用，但继续尝试点击...")

            # 尝试多种点击方式
            click_success = False

            # 方法 1: JS 点击
            try:
                self.driver.execute_script("arguments[0].click();", login_btn)
                logger.info("✅ (方法1: JS点击) 已点击 Next/Continue 按钮")
                click_success = True
            except Exception as e1:
                logger.warning(f"⚠️ 方法1失败: {e1}")

                # 方法 2: 直接点击
                try:
                    login_btn.click()
                    logger.info("✅ (方法2: 直接点击) 已点击 Next/Continue 按钮")
                    click_success = True
                except Exception as e2:
                    logger.warning(f"⚠️ 方法2失败: {e2}")

                    # 方法 3: 提交表单
                    try:
                        self.driver.execute_script("arguments[0].closest('form').submit();", login_btn)
                        logger.info("✅ (方法3: 表单提交) 已提交登录表单")
                        click_success = True
                    except Exception as e3:
                        logger.error(f"❌ 方法3失败: {e3}")

            if not click_success:
                self.save_debug_info("error_click_login_btn")
                raise Exception("❌ 所有点击方法均失败")

            time.sleep(3)
            self.save_debug_info("step4_after_login_submit")

        except Exception as e:
            self.save_debug_info("error_login_btn")
            raise Exception(f"❌ 点击最终 Continue 按钮失败: {e}")

        # ========== 步骤 5: 等待登录完成 ==========
        try:
            logger.info("⏳ 等待登录跳转...")

            WebDriverWait(self.driver, self.WAIT_TIME_AFTER_LOGIN).until(
                EC.url_to_be(self.HOME_URL)
            )

            if self.driver.current_url.startswith(self.HOME_URL):
                logger.info(f"✅ 登录成功，当前URL: {self.HOME_URL}")
                self.save_debug_info("step5_login_success")
                return True
            else:
                raise Exception(f"⚠️ 登录后未跳转到 HOME 页面: {self.driver.current_url}")

        except TimeoutException:
            self.save_debug_info("error_login_timeout")

            # 检查是否有错误信息
            try:
                error_selectors = [
                    (By.CSS_SELECTOR, ".cl-alert-danger"),
                    (By.CSS_SELECTOR, "[data-testid*='error']"),
                    (By.CSS_SELECTOR, "[role='alert']"),
                    (By.XPATH, "//*[contains(@class, 'error')]"),
                ]

                error_element = self.find_element_with_multiple_selectors(error_selectors, 2)

                if error_element and error_element.is_displayed():
                    error_text = error_element.text.strip()
                    raise Exception(f"❌ 登录失败: {error_text}")

            except Exception as e:
                if "登录失败" in str(e):
                    raise e

            # 检查当前 URL
            current_url = self.driver.current_url
            logger.error(f"❌ 登录超时 - 当前 URL: {current_url}")

            if "accounts.google.com" in current_url:
                raise Exception("❌ 检测到重定向至 Google 登录页面。脚本不支持 Google OAuth 登录，请确保您的 Pella 账号已设置密码，并支持直接使用邮箱+密码登录。")
            elif "login" in current_url:
                raise Exception("❌ 登录失败，仍停留在登录页面")
            else:
                logger.warning(f"⚠️ 未跳转到预期的 HOME URL，但已离开登录页: {current_url}")
                return True

    def get_server_url(self):
        """在 HOME 页面查找并点击服务器链接"""
        logger.info("🔍 在 HOME 页面查找服务器链接...")

        if not self.driver.current_url.startswith(self.HOME_URL):
            self.driver.get(self.HOME_URL)
            time.sleep(3)

        self.save_debug_info("get_server_url_start")

        try:
            server_link_selectors = [
                (By.CSS_SELECTOR, "a[href*='/server/']"),
                (By.XPATH, "//a[contains(@href, '/server/')]"),
            ]

            server_link = self.find_element_with_multiple_selectors(server_link_selectors, 15)

            if not server_link:
                self.save_debug_info("error_no_server_link")
                raise Exception("❌ 找不到服务器链接")

            server_link.click()

            WebDriverWait(self.driver, 10).until(EC.url_contains("/server/"))

            self.server_url = self.driver.current_url
            logger.info(f"✅ 成功跳转到服务器页面: {self.server_url}")
            self.save_debug_info("get_server_url_success")
            return True

        except Exception as e:
            self.save_debug_info("error_get_server_url")
            raise Exception(f"❌ 获取服务器 URL 失败: {e}")

    def renew_server(self):
        """执行续期流程"""
        if not self.server_url:
            raise Exception("❌ 缺少服务器 URL，无法执行续期")

        logger.info(f"👉 开始续期流程")
        self.driver.get(self.server_url)
        time.sleep(5)

        self.save_debug_info("renew_start")

        # 提取初始过期时间
        page_source = self.driver.page_source
        self.initial_expiry_details, self.initial_expiry_value = self.extract_expiry_days(page_source)
        logger.info(f"ℹ️ 初始过期时间: {self.initial_expiry_details}")

        if self.initial_expiry_value == -1.0:
            raise Exception("❌ 无法提取初始过期时间")

        # 续期循环
        try:
            # 多种续期按钮选择器
            renew_selectors = [
                # 旧格式: /renew/ 链接
                "a[href*='/renew/']:not(.opacity-50):not(.pointer-events-none)",
                # 新格式: Add XX Hours 按钮 (包含 cuty, shrink 等外部链接)
                "a[href*='cuty.io']",
                "a[href*='shrink-service.it']",
                "a[href*='linkvertise']",
                # 通用: 包含 "Add" 和 "Hours" 文本的链接
                "a:has-text('Hours')",
            ]

            renewed_count = 0
            original_window = self.driver.current_window_handle

            while True:
                renew_buttons = []

                # 尝试多种选择器
                for selector in renew_selectors:
                    try:
                        if ":has-text" in selector:
                            # XPath 方式查找包含文本的链接
                            renew_buttons = self.driver.find_elements(
                                By.XPATH,
                                "//a[contains(text(), 'Hours') or contains(., 'Hours')]"
                            )
                        else:
                            renew_buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)

                        if renew_buttons:
                            logger.info(f"✅ 使用选择器找到 {len(renew_buttons)} 个续期按钮: {selector}")
                            break
                    except Exception as e:
                        logger.debug(f"选择器 {selector} 失败: {e}")
                        continue

                if not renew_buttons:
                    break

                button = renew_buttons[0]
                renew_url = button.get_attribute('href')
                button_text = button.text.strip()

                logger.info(f"🚀 处理第 {renewed_count + 1} 个续期链接: {button_text}")
                logger.info(f"🔗 链接: {renew_url}")

                # 点击按钮打开新窗口
                self.driver.execute_script("window.open(arguments[0]);", renew_url)
                time.sleep(3)

                # 切换到新窗口
                if len(self.driver.window_handles) > 1:
                    self.driver.switch_to.window(self.driver.window_handles[-1])

                    # 处理广告页面 - 查找并点击 Continue 按钮
                    logger.info("🔍 在广告页面查找 Continue 按钮...")

                    continue_clicked = False
                    max_attempts = 3

                    for attempt in range(max_attempts):
                        try:
                            # 等待页面加载
                            time.sleep(3)

                            # 尝试多种 Continue 按钮选择器
                            continue_selectors = [
                                (By.XPATH, "//button[contains(translate(text(), 'CONTINUE', 'continue'), 'continue')]"),
                                (By.XPATH, "//a[contains(translate(text(), 'CONTINUE', 'continue'), 'continue')]"),
                                (By.XPATH, "//*[contains(translate(text(), 'CONTINUE', 'continue'), 'continue')]"),
                                (By.CSS_SELECTOR, "button.continue, a.continue"),
                                (By.CSS_SELECTOR, "button[class*='continue'], a[class*='continue']"),
                                (By.CSS_SELECTOR, "button[id*='continue'], a[id*='continue']"),
                                # cuty.io 特定选择器
                                (By.CSS_SELECTOR, "#go-link, .go-link"),
                                (By.XPATH, "//button[@id='go-link']"),
                                # shrink-service.it 特定选择器
                                (By.CSS_SELECTOR, "#btn-main, .btn-main"),
                                (By.XPATH, "//button[contains(@class, 'btn')]"),
                            ]

                            for selector_type, selector_value in continue_selectors:
                                try:
                                    continue_btn = WebDriverWait(self.driver, 5).until(
                                        EC.element_to_be_clickable((selector_type, selector_value))
                                    )
                                    if continue_btn and continue_btn.is_displayed():
                                        logger.info(f"✅ 找到 Continue 按钮: {selector_value}")
                                        self.driver.execute_script("arguments[0].click();", continue_btn)
                                        logger.info("✅ 已点击 Continue 按钮")
                                        continue_clicked = True
                                        break
                                except:
                                    continue

                            if continue_clicked:
                                break

                            logger.warning(f"⚠️ 第 {attempt + 1} 次尝试未找到 Continue 按钮，重试...")

                        except Exception as e:
                            logger.warning(f"⚠️ 查找 Continue 按钮出错: {e}")

                    if not continue_clicked:
                        logger.warning("⚠️ 未找到 Continue 按钮，但继续等待...")

                    # 等待续期完成
                    logger.info(f"⏳ 等待 {self.RENEW_WAIT_TIME} 秒...")
                    time.sleep(self.RENEW_WAIT_TIME)

                    # 关闭广告窗口
                    try:
                        self.driver.close()
                    except:
                        pass
                    self.driver.switch_to.window(original_window)
                else:
                    logger.warning("⚠️ 未检测到新窗口打开")

                logger.info(f"✅ 第 {renewed_count + 1} 个续期链接处理完成")
                renewed_count += 1

                # 刷新页面检查是否还有更多按钮
                self.driver.get(self.server_url)
                time.sleep(3)

            if renewed_count == 0:
                # 检查是否有禁用的按钮
                disabled_buttons = self.driver.find_elements(
                    By.CSS_SELECTOR,
                    "a[href*='/renew/'].opacity-50, a[href*='/renew/'].pointer-events-none, a.opacity-50, a.pointer-events-none"
                )

                # 检查是否有 "Links update every 24 hours" 提示
                page_source = self.driver.page_source
                if "Links update every" in page_source or "update every 24 hours" in page_source.lower():
                    return "⏳ 续期链接尚未刷新，请等待 24 小时后再试。"
                elif disabled_buttons:
                    return "⏳ 未找到可点击的续期按钮，可能今日已续期。"
                else:
                    return "⏳ 未找到任何续期按钮。"

            # 检查续期结果
            if renewed_count > 0:
                logger.info("🔄 检查续期结果...")
                self.driver.get(self.server_url)
                time.sleep(5)

                self.save_debug_info("renew_after_complete")

                final_expiry_details, final_expiry_value = self.extract_expiry_days(self.driver.page_source)
                logger.info(f"ℹ️ 最终过期时间: {final_expiry_details}")

                if final_expiry_value > self.initial_expiry_value:
                    days_added = final_expiry_value - self.initial_expiry_value

                    added_seconds = round(days_added * 24 * 3600)
                    added_days = int(added_seconds // (24 * 3600))
                    added_hours = int((added_seconds % (24 * 3600)) // 3600)
                    added_minutes = int((added_seconds % 3600) // 60)
                    added_string = f"{added_days} 天 {added_hours} 小时 {added_minutes} 分钟"

                    return (f"✅ 续期成功! 初始 {self.initial_expiry_details} -> 最终 {final_expiry_details} "
                            f"(共续期 {added_string})")
                elif final_expiry_value == self.initial_expiry_value:
                    return f"⚠️ 续期操作完成，但天数未增加 ({final_expiry_details})。"
                else:
                    return f"❌ 续期操作完成，但天数不升反降!"
            else:
                return "⏳ 未执行续期操作。"

        except Exception as e:
            self.save_debug_info("error_renew")
            raise Exception(f"❌ 续期流程错误: {e}")

    def run(self):
        """单个账号执行流程"""
        try:
            logger.info(f"⏳ 开始处理账号: {self.email}")

            if self.login():
                if self.get_server_url():
                    result = self.renew_server()
                    logger.info(f"📋 续期结果: {result}")
                    return True, result
                else:
                    return False, "❌ 无法获取服务器URL"
            else:
                return False, "❌ 登录失败"

        except Exception as e:
            error_msg = f"❌ 自动续期失败: {str(e)}"
            logger.error(error_msg)
            self.save_debug_info("error_final")
            return False, error_msg

        finally:
            if self.driver:
                self.driver.quit()

class MultiAccountManager:
    """多账号管理器"""

    def __init__(self):
        self.telegram_bot_token = os.getenv('TG_BOT_TOKEN', '')
        self.telegram_chat_id = os.getenv('TG_CHAT_ID', '')
        self.accounts = self.load_accounts()

    def load_accounts(self):
        accounts = []
        logger.info("⏳ 开始加载账号配置...")

        # 多账号格式
        accounts_str = os.getenv('PELLA_ACCOUNTS', os.getenv('LEAFLOW_ACCOUNTS', '')).strip()
        if accounts_str:
            try:
                logger.info("⏳ 尝试解析多账号配置")
                account_pairs = [pair.strip() for pair in re.split(r'[;,]', accounts_str) if pair.strip()]

                for i, pair in enumerate(account_pairs):
                    if ':' in pair:
                        email, password = pair.split(':', 1)
                        email = email.strip()
                        password = password.strip()

                        if email and password:
                            accounts.append({'email': email, 'password': password})
                            logger.info(f"✅ 成功添加第 {i+1} 个账号")

                if accounts:
                    logger.info(f"👉 成功加载 {len(accounts)} 个账号")
                    return accounts

            except Exception as e:
                logger.error(f"❌ 解析多账号配置失败: {e}")

        # 单账号格式
        single_email = os.getenv('PELLA_EMAIL', os.getenv('LEAFLOW_EMAIL', '')).strip()
        single_password = os.getenv('PELLA_PASSWORD', os.getenv('LEAFLOW_PASSWORD', '')).strip()

        if single_email and single_password:
            accounts.append({'email': single_email, 'password': single_password})
            logger.info("👉 加载了单个账号配置")
            return accounts

        logger.error("⚠️ 未找到有效的账号配置")
        raise ValueError("⚠️ 未找到有效的账号配置")

    def send_notification(self, results):
        """发送通知到Telegram"""
        if not self.telegram_bot_token or not self.telegram_chat_id:
            logger.info("⚠️ Telegram配置未设置，跳过通知")
            return

        try:
            success_count = sum(1 for _, success, result in results if success and "续期成功" in result)
            already_done_count = sum(1 for _, success, result in results if success and "未找到可点击" in result)
            failure_count = sum(1 for _, success, _ in results if not success)
            total_count = len(results)

            message = f"🎁 Pella自动续期通知\n\n"
            message += f"📋 共处理: {total_count} 个\n"
            message += f"✅ 续期成功: {success_count} 个\n"
            message += f"⏳ 已续期: {already_done_count} 个\n"
            message += f"❌ 失败: {failure_count} 个\n\n"

            for email, success, result in results:
                if success and "续期成功" in result:
                    status = "✅"
                elif "未找到可点击" in result:
                    status = "⏳"
                else:
                    status = "❌"

                if '@' in email:
                    local_part, domain = email.split('@', 1)
                    masked_email = local_part[:3] + "***@" + domain
                else:
                    masked_email = email[:3] + "***"

                short_result = result.split('\n')[0][:100]
                message += f"{status} {masked_email}: {short_result}\n"

            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            data = {"chat_id": self.telegram_chat_id, "text": message, "parse_mode": "HTML"}

            response = requests.post(url, data=data, timeout=10)
            if response.status_code == 200:
                logger.info("✅ Telegram 通知发送成功")
            else:
                logger.error(f"❌ Telegram 通知发送失败: {response.text}")

        except Exception as e:
            logger.error(f"❌ Telegram 通知发送出错: {e}")

    def run_all(self):
        """运行所有账号"""
        logger.info(f"👉 开始执行 {len(self.accounts)} 个账号的续期任务")

        results = []

        for i, account in enumerate(self.accounts, 1):
            logger.info(f"{'='*50}")
            logger.info(f"👉 处理第 {i}/{len(self.accounts)} 个账号: {account['email']}")

            success, result = False, "未运行"

            try:
                auto_renew = PellaAutoRenew(account['email'], account['password'])
                success, result = auto_renew.run()

                if i < len(self.accounts):
                    wait_time = 5
                    logger.info(f"⏳ 等待 {wait_time} 秒后处理下一个账号...")
                    time.sleep(wait_time)

            except Exception as e:
                error_msg = f"❌ 处理账号异常: {str(e)}"
                logger.error(error_msg)
                result = error_msg

            results.append((account['email'], success, result))

        logger.info(f"{'='*50}")
        self.send_notification(results)

        success_count = sum(1 for _, success, _ in results if success)
        return success_count == len(self.accounts), results

def main():
    """主函数"""
    try:
        manager = MultiAccountManager()
        overall_success, detailed_results = manager.run_all()

        if overall_success:
            logger.info("✅ 所有账号续期任务完成")
            exit(0)
        else:
            success_count = sum(1 for _, success, _ in detailed_results if success)
            logger.warning(f"⚠️ 部分账号续期失败: {success_count}/{len(detailed_results)} 成功")
            exit(0)

    except ValueError as e:
        logger.error(f"❌ 配置错误: {e}")
        exit(1)
    except Exception as e:
        logger.error(f"❌ 脚本执行出错: {e}")
        exit(1)

if __name__ == "__main__":
    main()
