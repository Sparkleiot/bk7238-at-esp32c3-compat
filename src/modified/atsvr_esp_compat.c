/*
 * atsvr_esp_compat.c
 *
 * ESP32-C3 / ESP-AT 兼容层 —— 在 Sparkleiot BK7238 AT SDK 之上补齐并纠正
 * AT 命令集，使上位机原有的 ESP-AT 驱动代码无需修改即可驱动本模组。
 *
 * 设计原则:
 *   1) 只新增命令 + 复用已有对外接口，不改动 ENV_PARAM 结构（避免 flash 布局变化）；
 *      新增的少量开关用本文件内的静态变量保存（掉电不保持，与 ESP-AT 的 _CUR 语义一致）。
 *   2) 已存在的同名命令无法通过重复注册覆盖（引擎会去重），因此
 *      "AT+CWJAP?" / "AT+CIPSTATUS?" / "AT+GMR" 等由原文件就地修正。
 *   3) 所有应答格式严格对齐 ESP-AT
 *      (https://docs.espressif.com/projects/esp-at/zh_CN/latest/esp32c3/AT_Command_Set/)。
 */
#include "atsvr_cmd.h"
#include "at_server.h"
#include "atsvr_wlan.h"
#include "atsvr_misc.h"
#include "atsvr_port.h"
#include "atsvr_comm.h"
#include "string.h"
#include "stdio.h"
#include "stdlib.h"
#include "typedef.h"
#include "wlan_defs_pub.h"
#include "wlan_ui_pub.h"
#include "rw_msg_pub.h"
#include "lwip/ip_addr.h"
/* 自研 AT+PING 所需的 ICMP Echo（见文件后半段注释） */
#include "lwip/sockets.h"
#include "lwip/icmp.h"
#include "lwip/ip.h"
#include "lwip/inet.h"
#include "lwip/inet_chksum.h"
#include "lwip/mem.h"
#include "lwip/sys.h"

#if CFG_USE_NETWORKING

/* 由 rtos 提供，_atsvr_func.c 中已在使用 */
extern size_t xPortGetFreeHeapSize(void);

/* atsvr_net_cmd.c 内部函数（用于 AT+CIPSTATUS 复用同一份链路状态输出） */
extern int network_link_status(void);
extern int network_cipstate_dump(void);

/* ------------------------------------------------------------------ */
/* 本文件内保存的运行时开关（不落 flash，语义等同 ESP-AT 的 _CUR 命令） */
/* ------------------------------------------------------------------ */
static uint8 s_cipdinfo    = 0;   /* AT+CIPDINFO   */
static uint8 s_ciprecvtype = 0;   /* AT+CIPRECVTYPE*/
static uint8 s_sleep_mode  = 0;   /* AT+SLEEP      */
static uint8 s_sysmsg      = 0;   /* AT+SYSMSG     */

#define ESP_AT_SEND_UINT(fmt, ...)                                        \
    do {                                                                  \
        int _n = snprintf(resultbuf, sizeof(resultbuf), fmt,              \
                          ##__VA_ARGS__);                                 \
        _n += snprintf(resultbuf + _n, sizeof(resultbuf) - _n, "%s",      \
                       ATSVR_CMD_RSP_SUCCEED);                            \
        atsvr_output_msg(resultbuf, _n);                                  \
    } while (0)

/* ================= 基础类 ================= */

/*
 * 应答标签推导: ESP-AT 要求响应里的前缀与「实际发出的命令名」一致。
 * 例如同一份查询逻辑被 AT+CIPSTA? / AT+CIPSTA_CUR? / AT+CIPSTA_DEF?
 * 三条命令共用，就必须分别回 +CIPSTA: / +CIPSTA_CUR: / +CIPSTA_DEF:。
 *
 * 引擎在调用处理函数时把命令原文放在 argv[0]（见 _at_server.c 的
 * handle_input/_atsvc_command_handle），因此这里直接从 argv[0] 里切出标签，
 * 无需为每条别名再写一份处理函数。
 *
 *   "AT+CWMODE_CUR?" -> "CWMODE_CUR"
 *   "AT+UART_DEF"    -> "UART_DEF"
 *   异常输入          -> fallback
 */
const char *atsvr_esp_tag(int argc, char **argv, char *buf, int bufsz, const char *fallback)
{
    const char *p;
    int n;

    if (argc < 1 || argv == NULL || argv[0] == NULL || buf == NULL || bufsz < 2) {
        return fallback;
    }
    p = argv[0];

    if ((p[0] == 'A' || p[0] == 'a') &&
        (p[1] == 'T' || p[1] == 't') && p[2] == '+') {
        p += 3;
    }

    n = (int)strlen(p);
    while (n > 0) {
        char c = p[n - 1];
        if (c == '?' || c == '=' || c == ' ' || c == '\t' || c == '\r' || c == '\n') {
            n--;
        } else {
            break;
        }
    }
    if (n <= 0 || n >= bufsz) {
        return fallback;
    }
    memcpy(buf, p, (size_t)n);
    buf[n] = '\0';
    return buf;
}

/* AT+SYSRAM?  ->  +SYSRAM:<remaining RAM size>,<minimum heap size> */
void atsvr_sysram_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "SYSRAM");
    int  n;
    if (argc != 1) {
        atsvr_cmd_rsp_error();
        return;
    }
#if CFG_OS_FREERTOS
    n = snprintf(resultbuf, sizeof(resultbuf), "+%s:%d,%d\r\n", tag,
                 (int)xPortGetFreeHeapSize(), 0);
#else
    n = snprintf(resultbuf, sizeof(resultbuf), "+%s:%d,%d\r\n", tag, 0, 0);
#endif
    n += snprintf(resultbuf + n, sizeof(resultbuf) - n, "%s", ATSVR_CMD_RSP_SUCCEED);
    atsvr_output_msg(resultbuf, n);
}

/* AT+SYSMSG / AT+SYSMSG? -> +SYSMSG:<state> */
void atsvr_sysmsg_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "SYSMSG");
    if (argc == 1) {
        ESP_AT_SEND_UINT("+%s:%d\r\n", tag, s_sysmsg);
        return;
    }
    if (argc == 2) {
        s_sysmsg = (uint8)atoi(argv[1]);
        atsvr_cmd_rsp_ok();
        return;
    }
    atsvr_cmd_rsp_error();
}

/* AT+SLEEP / AT+SLEEP? -> +SLEEP:<sleep mode> */
void atsvr_sleep_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "SLEEP");
    if (argc == 1) {
        ESP_AT_SEND_UINT("+%s:%d\r\n", tag, s_sleep_mode);
        return;
    }
    if (argc == 2) {
        s_sleep_mode = (uint8)atoi(argv[1]);
        atsvr_cmd_rsp_ok();
        return;
    }
    atsvr_cmd_rsp_error();
}

/* AT+UART_CUR / AT+UART_DEF -> +UART_CUR:<baudrate>,<databits>,<stopbits>,<parity>,<flow control> */
static void esp_uart_query(const char *tag)
{
    char resultbuf[160];
    int n = snprintf(resultbuf, sizeof(resultbuf), "+%s:%d,%d,%d,%d,%d\r\n", tag,
                     (int)g_env_param.uartinfo.baudrate,
                     g_env_param.uartinfo.databits,
                     g_env_param.uartinfo.stopbits,
                     g_env_param.uartinfo.parity,
                     g_env_param.uartinfo.flow_control);
    n += snprintf(resultbuf + n, sizeof(resultbuf) - n, "%s", ATSVR_CMD_RSP_SUCCEED);
    atsvr_output_msg(resultbuf, n);
}

static void esp_uart_set(int argc, char **argv, const char *tag, int persist)
{
    bk_uart_config_t uart_cfg;
    if (argc != 6) {
        atsvr_cmd_rsp_error();
        return;
    }
    /* flags 未赋默认值时必须清零，否则可能意外打开 UART 唤醒功能 */
    memset(&uart_cfg, 0, sizeof(uart_cfg));
    g_env_param.uartinfo.baudrate     = (uint32)atoi(argv[1]);
    g_env_param.uartinfo.databits     = (uint8)atoi(argv[2]);
    g_env_param.uartinfo.stopbits     = (uint8)atoi(argv[3]);
    g_env_param.uartinfo.parity       = (uint8)atoi(argv[4]);
    g_env_param.uartinfo.flow_control = (uint8)atoi(argv[5]);

    uart_cfg.baud_rate    = g_env_param.uartinfo.baudrate;
    uart_cfg.data_width   = g_env_param.uartinfo.databits;
    uart_cfg.stop_bits    = g_env_param.uartinfo.stopbits;
    uart_cfg.parity       = g_env_param.uartinfo.parity;
    uart_cfg.flow_control = g_env_param.uartinfo.flow_control;
    bk_uart_initialize(AT_UART_PORT_CFG, &uart_cfg, NULL);

    /* ESP-AT: UART_DEF 必定落 flash；UART_CUR 只在 SYSSTORE=1 时落 */
    if (persist || g_env_param.sysstore) {
        write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *)&g_env_param);
    }
    (void)tag;
    atsvr_cmd_rsp_ok();
}

void atsvr_uart_cur_command(int argc, char **argv)
{
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "UART_CUR");
    if (argc == 1) { esp_uart_query(tag); return; }
    esp_uart_set(argc, argv, tag, 0);
}

void atsvr_uart_def_command(int argc, char **argv)
{
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "UART_DEF");
    if (argc == 1) { esp_uart_query(tag); return; }
    esp_uart_set(argc, argv, tag, 1);
}

/* ================= Wi-Fi 类 ================= */

/* AT+CWJAP? -> 未连接: "No AP"；已连接: +CWJAP:"ssid","bssid",<ch>,<rssi>,... */
void atsvr_cwjap_query_command(int argc, char **argv)
{
    LinkStatusTypeDef link;
    char resultbuf[256];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWJAP");
    int  n;

    if (argc != 1) {
        atsvr_cmd_rsp_error();
        return;
    }

    memset(&link, 0, sizeof(link));
    bk_wlan_get_link_status(&link);

    if (link.conn_state == 0) {
        n  = snprintf(resultbuf, sizeof(resultbuf), "No AP\r\n");
        n += snprintf(resultbuf + n, sizeof(resultbuf) - n, "%s", ATSVR_CMD_RSP_SUCCEED);
        atsvr_output_msg(resultbuf, n);
        return;
    }

    n  = snprintf(resultbuf, sizeof(resultbuf),
                  "+%s:\"%s\",\"%02x:%02x:%02x:%02x:%02x:%02x\",%d,%d,0,0,0,0,0\r\n",
                  tag,
                  (char *)link.ssid,
                  link.bssid[0], link.bssid[1], link.bssid[2],
                  link.bssid[3], link.bssid[4], link.bssid[5],
                  link.channel, (int)link.wifi_strength);
    n += snprintf(resultbuf + n, sizeof(resultbuf) - n, "%s", ATSVR_CMD_RSP_SUCCEED);
    atsvr_output_msg(resultbuf, n);
}

/* AT+CWAUTOCONN / ? -> +CWAUTOCONN:<enable> */
void atsvr_cwautoconn_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWAUTOCONN");
    if (argc == 1) {
        ESP_AT_SEND_UINT("+%s:%d\r\n", tag, g_env_param.wifimode.autoconnect ? 1 : 0);
        return;
    }
    if (argc == 2) {
        g_env_param.wifimode.autoconnect = (uint8)(atoi(argv[1]) ? 1 : 0);
        if (g_env_param.sysstore) {
            write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *)&g_env_param);
        }
        atsvr_cmd_rsp_ok();
        return;
    }
    atsvr_cmd_rsp_error();
}

/* AT+CWCOUNTRY / ? -> +CWCOUNTRY:<country code>,<start channel>,<end channel>,<policy> */
void atsvr_cwcountry_command(int argc, char **argv)
{
    wifi_country_t cc;
    char resultbuf[160];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWCOUNTRY");
    int  n;

    if (argc == 1) {
        memset(&cc, 0, sizeof(cc));
        if (bk_wlan_get_country(&cc) != kNoErr) {
            atsvr_cmd_rsp_error();
            return;
        }
        n  = snprintf(resultbuf, sizeof(resultbuf), "+%s:%s,%d,%d,%d\r\n",
                      tag, cc.cc, cc.schan, (int)cc.schan + (int)cc.nchan - 1, (int)cc.policy);
        n += snprintf(resultbuf + n, sizeof(resultbuf) - n, "%s", ATSVR_CMD_RSP_SUCCEED);
        atsvr_output_msg(resultbuf, n);
        return;
    }
    if (argc == 5) {
        memset(&cc, 0, sizeof(cc));
        cc.cc[0] = argv[1][0];
        cc.cc[1] = argv[1][1];
        cc.cc[2] = '\0';
        cc.schan = (uint8_t)atoi(argv[2]);
        cc.nchan = (uint8_t)(atoi(argv[3]) - atoi(argv[2]) + 1);
        cc.policy = (wifi_country_policy_t)atoi(argv[4]);
        bk_wlan_set_country(&cc);
        atsvr_cmd_rsp_ok();
        return;
    }
    atsvr_cmd_rsp_error();
}

/* ================= TCP/IP 类 ================= */

/* AT+CIPMODE? -> +CIPMODE:<mode> */
void atsvr_cipmode_query_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CIPMODE");
    if (argc != 1) {
        atsvr_cmd_rsp_error();
        return;
    }
    ESP_AT_SEND_UINT("+%s:%d\r\n", tag,
                     g_env_param.net_transmission_mode == ATSVR_PASSTHROUGH_MODE ? 1 : 0);
}

/* AT+CIPDINFO / ? -> +CIPDINFO:<enable> */
void atsvr_cipdinfo_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CIPDINFO");
    if (argc == 1) {
        ESP_AT_SEND_UINT("+%s:%d\r\n", tag, s_cipdinfo);
        return;
    }
    if (argc == 2) {
        s_cipdinfo = (uint8)(atoi(argv[1]) ? 1 : 0);
        atsvr_cmd_rsp_ok();
        return;
    }
    atsvr_cmd_rsp_error();
}

/* AT+CIPRECVTYPE / AT+CIPRECVMODE / ? -> +<name>:<mode> */
void atsvr_ciprecvtype_command(int argc, char **argv)
{
    char resultbuf[128];
    char tagbuf[24];
    const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CIPRECVTYPE");
    if (argc == 1) {
        ESP_AT_SEND_UINT("+%s:%d\r\n", tag, s_ciprecvtype);
        return;
    }
    if (argc == 2) {
        s_ciprecvtype = (uint8)(atoi(argv[1]) ? 1 : 0);
        atsvr_cmd_rsp_ok();
        return;
    }
    atsvr_cmd_rsp_error();
}

/* AT+CIPSTATUS -> STATUS:<stat> [+CIPSTATUS:...] */
void atsvr_cipstatus_command(int argc, char **argv)
{
    (void)argv;
    if (argc != 1) {
        atsvr_cmd_rsp_error();
        return;
    }
    network_link_status();
    atsvr_cmd_rsp_ok();
}

/* AT+CIPSTATE -> +CIPSTATE:<link ID>,<"type">,<"remote IP">,<remote port>,<local port>,<tetype>
 * 新版 ESP-AT 用 CIPSTATE 替代了旧的 CIPSTATUS，这里两个都提供 */
void atsvr_cipstate_command(int argc, char **argv)
{
    (void)argv;
    if (argc != 1) {
        atsvr_cmd_rsp_error();
        return;
    }
    network_cipstate_dump();
    atsvr_cmd_rsp_ok();
}

/* ==================================================================
 * AT+PING 所需的 ICMP Echo 实现（本项目自研，独立于 lwIP 的 ping.c）
 *
 * 为什么自己写而不改造 SDK 自带的 ping.c:
 *   SDK 自带的 beken378/.../apps/ping/ping.c 属 RT-Thread / lwIP 社区的
 *   **GPL v2/v3** 传染性组件。为把 ESP-AT 的 `+PING:<ms>` 语义补上，
 *   早期版本直接改了那个文件（新增 at_ping_ex）。这有两个不可接受的后果：
 *     1) GPL 传染性会把整个衍生作品拖成 GPL，与本仓库"自有内容走 MIT"的
 *        双轨许可声明冲突；
 *     2) 该文件一旦从仓库移除，src/apply.sh 仍在 cp 它，`set -e` 下脚本
 *        在中途失败，**后面 8 个文件（HAL_TLS / HAL_TCP / network_socket /
 *        application.mk / sys_config 等）根本不会被覆盖**，克隆者会编出一个
 *        缺关键修复（甚至编不过）的固件。
 *   因此这里改为在本文件里独立实现一份 ICMP Echo：只依赖 lwIP 的公开
 *   socket API（lwip_socket / lwip_sendto / lwip_recvfrom），不触碰也不
 *   复制 ping.c 的任何代码，SDK 侧的 ping.c 保持厂商原样、零改动。
 *
 * 与原厂 at_ping 的差别（正是 ESP-AT 语义所需）:
 *   - 原厂把 "N bytes from ... time=M ticks" 直接 atsvr_output_msg 刷屏，
 *     上位机拿不到可解析的 RTT；本实现 quiet=1 时全程静默，只把 RTT 毫秒
 *     写进 *out_ms，由 AT 层回 "+PING:<ms>"。
 *   - 原厂用 tick 差值（1 tick = 1ms，实际为 10ms 定时器粒度时误差大），
 *     本实现直接用 sys_now() 的毫秒差。
 * ================================================================== */
#define AT_PING_RCV_TIMEO_MS 3000
#define AT_PING_ID           0x4154   /* 'AT'，与原厂 PING_ID 不同以免串扰 */
#define AT_PING_DATA_LEN     16

extern void atsvr_output_msg(char *msg, unsigned int msg_len);

static uint16 s_at_ping_seq = 0;

static void at_ping_fill_echo(struct icmp_echo_hdr *iecho, uint16_t len)
{
    int i;
    int data_len = (int)len - (int)sizeof(struct icmp_echo_hdr);

    ICMPH_TYPE_SET(iecho, ICMP_ECHO);
    ICMPH_CODE_SET(iecho, 0);
    iecho->chksum = 0;
    iecho->id     = AT_PING_ID;
    iecho->seqno  = htons(++s_at_ping_seq);

    for (i = 0; i < data_len; i++) {
        ((char *)iecho)[sizeof(struct icmp_echo_hdr) + i] = (char)i;
    }

    iecho->chksum = inet_chksum(iecho, len);
}

/*
 * 发一次 ICMP Echo 并等回包。
 *   target      目标 IP 字符串（点分十进制；域名请先在 AT 层解析好）
 *   out_ms      成功时写入 RTT 毫秒（>=0），失败时写入 -1
 *   timeout_ms  收包超时
 * 返回 0 = 收到匹配 id/seq 的 Echo Reply；-1 = 超时或出错
 */
int atsvr_icmp_ping_once(const char *target, int *out_ms, int timeout_ms)
{
    int s, len, ret = -1;
    u32_t t_start;
    u32_t target_u32;
    struct timeval tv;
    struct sockaddr_in to;
    ip_addr_t target_addr;
    struct icmp_echo_hdr *iecho;
    uint16 ping_size = (uint16)(sizeof(struct icmp_echo_hdr) + AT_PING_DATA_LEN);
    char buf[128];

    if (out_ms) {
        *out_ms = -1;
    }
    if (target == NULL || target[0] == '\0') {
        return -1;
    }

#if (LWIP_IPV4 && LWIP_IPV6)
    /* 本SDK 同时开了 IPv4/IPv6，ip_addr_t 是 { union{u_addr}, type }。
       必须显式声明这是 V4 地址，否则 lwIP 发送时会按 type 判成别的地址族，
       表现为 sendto 成功但永远收不到回包。inet_aton 宏只填 u_addr.ip4。 */
    memset(&target_addr, 0, sizeof(target_addr));
    target_addr.type = IPADDR_TYPE_V4;
    if (ip4addr_aton(target, &target_addr.u_addr.ip4) == 0) {
        return -1;
    }
    target_u32 = target_addr.u_addr.ip4.addr;
#else
    if (inet_aton(target, &target_addr) == 0) {
        return -1;
    }
    target_u32 = target_addr.addr;
#endif

    s = lwip_socket(AF_INET, SOCK_RAW, IP_PROTO_ICMP);
    if (s < 0) {
        return -1;
    }

    tv.tv_sec  = timeout_ms / 1000;
    tv.tv_usec = (timeout_ms % 1000) * 1000;
    lwip_setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

    iecho = (struct icmp_echo_hdr *)mem_malloc(ping_size);
    if (iecho == NULL) {
        lwip_close(s);
        return -1;
    }

    memset(&to, 0, sizeof(to));
    to.sin_len      = sizeof(to);
    to.sin_family   = AF_INET;
    to.sin_addr.s_addr = target_u32;

    at_ping_fill_echo(iecho, ping_size);
    t_start = sys_now();

    if (lwip_sendto(s, iecho, ping_size, 0, (struct sockaddr *)&to, sizeof(to)) == (int)ping_size) {
        for (;;) {
            int fromlen = sizeof(struct sockaddr_in);
            len = lwip_recvfrom(s, buf, sizeof(buf), 0, (struct sockaddr *)&to, (socklen_t *)&fromlen);
            if (len <= 0) {
                break;                      /* 超时（SO_RCVTIMEO）或出错 */
            }
            if (len >= (int)(sizeof(struct ip_hdr) + sizeof(struct icmp_echo_hdr))) {
                struct ip_hdr *iphdr   = (struct ip_hdr *)buf;
                struct icmp_echo_hdr *iecho_r = (struct icmp_echo_hdr *)(buf + (IPH_HL(iphdr) * 4));
                if ((iecho_r->id == AT_PING_ID) && (iecho_r->seqno == htons(s_at_ping_seq))) {
                    if (out_ms) {
                        u32_t d = sys_now() - t_start;
                        *out_ms = (d > 0x7FFF) ? 0x7FFF : (int)d;
                    }
                    ret = 0;
                    break;
                }
            }
        }
    }

    mem_free(iecho);
    lwip_close(s);
    return ret;
}

/* ================= 命令注册 ================= */

const struct _atsvr_command atsvc_esp_compat_table[] = {
    /* 基础 */
    ATSVR_CMD_HADLER("AT+SYSRAM?",  "AT+SYSRAM?",  atsvr_sysram_command),
    ATSVR_CMD_HADLER("AT+SYSRAM",   "AT+SYSRAM",   atsvr_sysram_command),
    ATSVR_CMD_HADLER("AT+SYSMSG?",  "AT+SYSMSG?",  atsvr_sysmsg_command),
    ATSVR_CMD_HADLER("AT+SYSMSG",   "AT+SYSMSG=<state>", atsvr_sysmsg_command),
    ATSVR_CMD_HADLER("AT+SLEEP?",   "AT+SLEEP?",   atsvr_sleep_command),
    ATSVR_CMD_HADLER("AT+SLEEP",    "AT+SLEEP=<sleep mode>", atsvr_sleep_command),
    ATSVR_CMD_HADLER("AT+UART_CUR?", "AT+UART_CUR?", atsvr_uart_cur_command),
    ATSVR_CMD_HADLER("AT+UART_CUR",  "AT+UART_CUR=<baudrate>,<databits>,<stopbits>,<parity>,<flow>", atsvr_uart_cur_command),
    ATSVR_CMD_HADLER("AT+UART_DEF?", "AT+UART_DEF?", atsvr_uart_def_command),
    ATSVR_CMD_HADLER("AT+UART_DEF",  "AT+UART_DEF=<baudrate>,<databits>,<stopbits>,<parity>,<flow>", atsvr_uart_def_command),

    /* Wi-Fi */
    ATSVR_CMD_HADLER("AT+CWJAP?",      "AT+CWJAP?",      atsvr_cwjap_query_command),
    ATSVR_CMD_HADLER("AT+CWJAP_CUR?",  "AT+CWJAP_CUR?",  atsvr_cwjap_query_command),
    ATSVR_CMD_HADLER("AT+CWJAP_DEF?",  "AT+CWJAP_DEF?",  atsvr_cwjap_query_command),
    ATSVR_CMD_HADLER("AT+CWAUTOCONN?", "AT+CWAUTOCONN?", atsvr_cwautoconn_command),
    ATSVR_CMD_HADLER("AT+CWAUTOCONN",  "AT+CWAUTOCONN=<enable>", atsvr_cwautoconn_command),
    ATSVR_CMD_HADLER("AT+CWCOUNTRY?",  "AT+CWCOUNTRY?",  atsvr_cwcountry_command),
    ATSVR_CMD_HADLER("AT+CWCOUNTRY",   "AT+CWCOUNTRY=<cc>,<start ch>,<end ch>,<policy>", atsvr_cwcountry_command),

    /* TCP/IP */
    ATSVR_CMD_HADLER("AT+CIPMODE?",   "AT+CIPMODE?",   atsvr_cipmode_query_command),
    ATSVR_CMD_HADLER("AT+CIPDINFO?",  "AT+CIPDINFO?",  atsvr_cipdinfo_command),
    ATSVR_CMD_HADLER("AT+CIPDINFO",   "AT+CIPDINFO=<enable>", atsvr_cipdinfo_command),
    ATSVR_CMD_HADLER("AT+CIPRECVTYPE?", "AT+CIPRECVTYPE?", atsvr_ciprecvtype_command),
    ATSVR_CMD_HADLER("AT+CIPRECVTYPE",  "AT+CIPRECVTYPE=<mode>", atsvr_ciprecvtype_command),
    /* ESP-AT 旧名（部分版本仍在使用），与 CIPRECVTYPE 等价 */
    ATSVR_CMD_HADLER("AT+CIPRECVMODE?", "AT+CIPRECVMODE?", atsvr_ciprecvtype_command),
    ATSVR_CMD_HADLER("AT+CIPRECVMODE",  "AT+CIPRECVMODE=<mode>", atsvr_ciprecvtype_command),
    ATSVR_CMD_HADLER("AT+CIPSTATUS",  "AT+CIPSTATUS",  atsvr_cipstatus_command),
    ATSVR_CMD_HADLER("AT+CIPSTATE?",  "AT+CIPSTATE?",  atsvr_cipstate_command),
    ATSVR_CMD_HADLER("AT+CIPSTATE",   "AT+CIPSTATE",   atsvr_cipstate_command),
};

void atsvr_esp_compat_init(void)
{
    atsvr_register_commands(atsvc_esp_compat_table,
                            sizeof(atsvc_esp_compat_table) / sizeof(struct _atsvr_command));
}

#endif /* CFG_USE_NETWORKING */
