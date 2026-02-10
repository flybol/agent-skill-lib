/**
 * 用户 Cookie 管理模块
 * 负责创建、读取和验证用户标识 cookie
 */

const COOKIE_NAME = 'user_id';
const COOKIE_MAX_AGE = 365 * 24 * 60 * 60; // 1年（秒）

/**
 * 生成6位随机字符串（字母+数字）
 */
function generateUserId() {
    const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
    let result = '';
    for (let i = 0; i < 6; i++) {
        result += chars.charAt(Math.floor(Math.random() * chars.length));
    }
    return result;
}

/**
 * 设置 cookie
 * @param {string} name - cookie 名称
 * @param {string} value - cookie 值
 * @param {number} maxAge - 最大有效时间（秒）
 */
function setCookie(name, value, maxAge) {
    // 获取当前域名，确保 cookie 在所有子域名下都有效
    // 对于 localhost 或 IP 地址，不设置 domain（浏览器默认行为）
    // 对于域名（如 example.com），设置为 .example.com（带前导点，使 cookie 在所有子域名下有效）
    let domain = '';
    const hostname = window.location.hostname;

    // 只有非 localhost 且非 IP 地址的域名才设置 domain
    if (hostname !== 'localhost' && !/^[\d.]+$/.test(hostname)) {
        // 移除端口号，并添加前导点（使 cookie 在所有子域名下有效）
        domain = `; domain=.${hostname.split(':')[0]}`;
    }

    document.cookie = `${name}=${value}; path=/; max-age=${maxAge}; SameSite=Lax${domain}`;
}

/**
 * 获取 cookie 值
 * @param {string} name - cookie 名称
 * @returns {string|null} cookie 值，不存在返回 null
 */
function getCookie(name) {
    const nameEQ = name + '=';
    const cookies = document.cookie.split(';');

    for (let i = 0; i < cookies.length; i++) {
        let cookie = cookies[i];
        while (cookie.charAt(0) === ' ') {
            cookie = cookie.substring(1, cookie.length);
        }
        if (cookie.indexOf(nameEQ) === 0) {
            return cookie.substring(nameEQ.length, cookie.length);
        }
    }
    return null;
}

/**
 * 检查浏览器是否支持 cookie
 * 通过尝试设置一个测试 cookie 来验证
 * @returns {boolean} 是否支持 cookie
 */
function checkCookieSupport() {
    const testCookie = 'cookie_test';
    try {
        // 创建测试 cookie
        document.cookie = `${testCookie}=1; path=/`;

        // 检查是否能读取
        const supported = document.cookie.indexOf(`${testCookie}=`) !== -1;

        // 删除测试 cookie
        document.cookie = `${testCookie}=; path=/; max-age=0`;

        return supported;
    } catch (e) {
        return false;
    }
}

/**
 * 获取或创建用户 ID
 * @returns {{userId: string|null, isNew: boolean, error: string|null}}
 * - userId: 用户标识（格式：user_xxxxxx）
 * - isNew: 是否是新创建的用户
 * - error: 错误信息（如果有）
 */
function getOrCreateUserId() {
    // 首先检查浏览器是否支持 cookie
    if (!checkCookieSupport()) {
        return {
            userId: null,
            isNew: false,
            error: '您的浏览器不支持 cookie，无法正常使用本应用'
        };
    }

    // 尝试获取现有用户 ID
    let userId = getCookie(COOKIE_NAME);

    if (userId) {
        // 验证格式（应为 user_ 开头 + 6位字符）
        if (userId.startsWith('user_') && userId.length === 11) {
            return {
                userId: userId,
                isNew: false,
                error: null
            };
        }
        // 格式不正确，重新创建
    }

    // 创建新用户 ID
    const randomPart = generateUserId();
    userId = `user_${randomPart}`;

    try {
        setCookie(COOKIE_NAME, userId, COOKIE_MAX_AGE);

        // 验证是否成功设置
        const verify = getCookie(COOKIE_NAME);
        if (verify === userId) {
            return {
                userId: userId,
                isNew: true,
                error: null
            };
        } else {
            return {
                userId: null,
                isNew: false,
                error: '无法保存用户标识，请检查浏览器设置'
            };
        }
    } catch (e) {
        return {
            userId: null,
            isNew: false,
            error: '无法保存用户标识，请检查浏览器设置'
        };
    }
}

/**
 * 清除用户 ID cookie（用于测试或登出）
 */
function clearUserId() {
    // 使用与 setCookie 相同的 domain 逻辑
    let domain = '';
    const hostname = window.location.hostname;

    if (hostname !== 'localhost' && !/^[\d.]+$/.test(hostname)) {
        domain = `; domain=.${hostname.split(':')[0]}`;
    }

    document.cookie = `${COOKIE_NAME}=; path=/; max-age=0${domain}`;
}

export {
    getOrCreateUserId,
    clearUserId,
    checkCookieSupport,
    getCookie,
    COOKIE_NAME
};
