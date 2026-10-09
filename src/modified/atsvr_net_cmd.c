
#include "lwip/netdb.h"

#include "_atsvr_func.h"
#include "_at_server.h"
#include "atsvr_comm.h"
#include "string.h"
#include "stdio.h"
#include "mem_pub.h"

#include "atsvr_misc.h"
#include "atsvr_port.h"
#include "at_server.h"
#include "atsvr_net_cmd.h"
#include "wlan_ui_pub.h"
#include "network_app.h"
#include "drv_model_pub.h"
#include "atsvr_wlan.h"
#include "dns.h"
#include "rtc.h"
#include "ntp.h"
#if CFG_USE_TCPUDP
static int g_conmode = 0; //0:单连接;1:多连接

/* 供 network_app.c 的接收线程使用: +IPD 前缀需要区分单/多连接 */
int atsvr_get_conmode(void)
{
	return g_conmode;
}

extern int create_network_task();
extern int network_link_status();
extern void rtos_thread_msleep(uint32_t milliseconds);

/* 原厂 get_domainip(): 域名 -> IPv4 字符串, 成功返回 1 */
extern int get_domainip(const char *hname, char *hostip);
/* ping.c 新增: quiet=1 时不打印原厂调试行, 仅通过 out_ms 回传 RTT(毫秒) */
extern int at_ping_ex(char *target_name, uint32_t times, size_t size, int quiet, int *out_ms);

/* ESP-AT 的 AT+CIPSTART / AT+PING 都允许直接填域名, 这里统一解析一次。
   host 已是 IPv4 字面量则直接沿用, 否则走 DNS。成功返回 1 并写入 ipout。
   注: host 用 char* 而非 const char* —— 原厂 judge_the_string_is_ipv4_string
   的形参没有 const, 传 const 会被 -Werror=discarded-qualifiers 拦下。 */
static int atsvr_resolve_host(char *host, char *ipout)
{
	if (host == NULL || ipout == NULL || host[0] == '\0')
	{
		return 0;
	}

	if (judge_the_string_is_ipv4_string(host) == 0)
	{
		strncpy(ipout, host, 15);
		ipout[15]		= '\0';
		return 1;
	}

	if (get_domainip(host, ipout))
	{
		return (judge_the_string_is_ipv4_string(ipout) == 0) ? 1 : 0;
	}

	return 0;
}

static void _atsvr_BIPSTATUS_handle(int argc, char * *argv)
{
	if (argc != 1)
	{
		atsvr_cmd_rsp_error();
		return;
	}

	/* ESP-AT 的 AT+CIPSTATUS/AT+CIPSTATUS? 都以 OK 结束 */
	network_link_status();
	atsvr_cmd_rsp_ok();
}

static void _atsvr_BIPSTART_handle(int argc, char * *argv)
{
	pm_socket_info_t rcvmsg;
	rcvmsg.linktype = 0;

	if (g_conmode)
	{
		if (argc < 5)
		{
			atsvr_cmd_rsp_error();
			return;
		}

		rcvmsg.linkid		= atoi(argv[1]);

		if ((strcmp(argv[2], "TCP") == 0) || (strcmp(argv[2], "tcp") == 0))
		{
			rcvmsg.type 		= NETWORK_TCP;
		}
		else if ((strcmp(argv[2], "UDP") == 0) || (strcmp(argv[2], "udp") == 0))
		{
			rcvmsg.type 		= NETWORK_UDP;
		}
		else if ((strcmp(argv[2], "TLS") == 0) || (strcmp(argv[2], "tls") == 0)
			|| (strcmp(argv[2], "SSL") == 0) || (strcmp(argv[2], "ssl") == 0))
		{
			rcvmsg.type 		= NETWORK_TLS;
		}
		else if ((strcmp(argv[2], "DTLS") == 0) || (strcmp(argv[2], "dtls") == 0))
		{
			rcvmsg.type 		= NETWORK_DTLS;
		}
		else
		{
			ATSVRLOG("argc:2 error\r\n");
			atsvr_cmd_rsp_error();
			return;
		}

		/* ESP-AT 允许直接写域名(如 AT+CIPSTART="TCP","www.baidu.com",80),
		   原厂只接受 IPv4 字面量 —— 这里补上解析。 */
		if (atsvr_resolve_host(argv[3], rcvmsg.remoteip) == 0)
		{
			ATSVRLOG("argc:3 error\r\n");
			atsvr_cmd_rsp_error();
			return;
		}

		rcvmsg.port 		= atoi(argv[4]);
		if (argc >= 6)
		{
			switch (rcvmsg.type)
			{
				case NETWORK_TCP:
				case NETWORK_TLS:
					rcvmsg.keepalive = atoi(argv[5]);
					break;

				case NETWORK_UDP:
				case NETWORK_DTLS:
					rcvmsg.localport = atoi(argv[5]);
					break;
			}
		}

		if (argc >= 7)
		{
			switch (rcvmsg.type)
			{
				case NETWORK_UDP:
				case NETWORK_DTLS:
					/* ESP-AT 第 7 参是 udp mode(数字), 原厂误套 IPv4 校验导致永远 ERROR */
					rcvmsg.udpmode = atoi(argv[6]);
					break;

				default:
					if (judge_the_string_is_ipv4_string(argv[6]) == 0)
					{
						strcpy(rcvmsg.localip, argv[6]);
					}
					else
					{
						ATSVRLOG("argc:7 error\r\n");
						atsvr_cmd_rsp_error();
						return;
					}
					break;
			}
		}

		if (argc >= 8)
		{
			if (rcvmsg.type == NETWORK_UDP || rcvmsg.type == NETWORK_DTLS)
			{

				if (judge_the_string_is_ipv4_string(argv[7]) == 0)
				{
					strcpy(rcvmsg.localip, argv[7]);
				}
				else
				{
					ATSVRLOG("argc:9 error\r\n");
					atsvr_cmd_rsp_error();
					return;
				}
			}
			else
			{

				ATSVRLOG("argc:9 error\r\n");
				atsvr_cmd_rsp_error();
				return;
			}
		}

		if (rcvmsg.linkid > 5 || isconnected_network(rcvmsg.linkid))
		{
			ATSVRLOG("linkid error\r\n");
			atsvr_cmd_rsp_error();
			return;
		}
		else
		{
			rtos_push_to_queue(&network_msg_que, &rcvmsg, BEKEN_NO_WAIT);
		}
	}
	else
	{
		if (argc < 4)
		{
			atsvr_cmd_rsp_error();
			return;
		}

		if ((strcmp(argv[1], "TCP") == 0) || (strcmp(argv[1], "tcp") == 0))
		{
			rcvmsg.type 		= NETWORK_TCP;
		}
		else if ((strcmp(argv[1], "UDP") == 0) || (strcmp(argv[1], "udp") == 0))
		{
			rcvmsg.type 		= NETWORK_UDP;
		}
		else if ((strcmp(argv[1], "TLS") == 0) || (strcmp(argv[1], "tls") == 0)
			|| (strcmp(argv[1], "SSL") == 0) || (strcmp(argv[1], "ssl") == 0))
		{
			rcvmsg.type 		= NETWORK_TLS;
		}
		else if ((strcmp(argv[1], "DTLS") == 0) || (strcmp(argv[1], "dtls") == 0))
		{
			rcvmsg.type 		= NETWORK_DTLS;
		}
		else
		{
			ATSVRLOG("\r\nargc:2 error\r\n");
			atsvr_cmd_rsp_error();
			return;
		}

		/* 单连接分支同样允许域名: AT+CIPSTART="TCP","www.baidu.com",80
		   (CIPMUX=1 分支已在上方处理, 这个分支原厂同样只收 IPv4 字面量) */
		if (atsvr_resolve_host(argv[2], rcvmsg.remoteip) == 0)
		{
			ATSVRLOG("argc:3 error\r\n");
			atsvr_cmd_rsp_error();
			return;
		}

		rcvmsg.port 		= atoi(argv[3]);
		if (argc >= 5)
		{
			switch (rcvmsg.type)
			{
				case NETWORK_TCP:
				case NETWORK_TLS:
					rcvmsg.keepalive = atoi(argv[4]);
					break;

				case NETWORK_UDP:
				case NETWORK_DTLS:
					rcvmsg.localport = atoi(argv[4]);
					break;
			}
		}

		if (argc >= 6)
		{
			switch (rcvmsg.type)
			{
				case NETWORK_UDP:
				case NETWORK_DTLS:
					/* ESP-AT 第 6 参是 udp mode(数字), 原厂误套 IPv4 校验导致永远 ERROR */
					rcvmsg.udpmode = atoi(argv[5]);
					break;

				default:
					if (judge_the_string_is_ipv4_string(argv[5]) == 0)
					{
						strcpy(rcvmsg.localip, argv[5]);
					}
					else
					{
						ATSVRLOG("argc:6 error\r\n");
						atsvr_cmd_rsp_error();
						return;
					}
					break;
			}
		}

		if (argc >= 7)
		{
			if (rcvmsg.type == NETWORK_UDP || rcvmsg.type == NETWORK_DTLS)
			{
				if (judge_the_string_is_ipv4_string(argv[6]) == 0)
				{
					strcpy(rcvmsg.localip, argv[6]);
				}
				else
				{
					ATSVRLOG("argc:6 error\r\n");
					atsvr_cmd_rsp_error();
					return;
				}
			}
		}

		rcvmsg.linkid		= 0;

		if (rcvmsg.linkid > 5 || isconnected_network(rcvmsg.linkid))
		{
			ATSVRLOG("linkid error\r\n");
			atsvr_cmd_rsp_error();
			return;
		}
		else
		{
			rtos_push_to_queue(&network_msg_que, &rcvmsg, BEKEN_NO_WAIT);
		}
	}
	return;
}


static void _atsvr_BIPCLOSE_handle(int argc, char * *argv)
{
	int linkid=0;

	if(g_conmode){
		if (argc < 2)
		{
			atsvr_cmd_rsp_error();
			return;
		}

		linkid = atoi(argv[1]);

		/* ESP-AT 兼容修复: AT+CIPCLOSE=5 的语义是"关闭所有连接"(原厂把 5
		 * 当普通 linkid, 而 link5 恰是服务端槽 —— CIPSERVER 未开时必 ERROR,
		 * 连接永远关不掉, 残留连接会把后续 CIPSTART 全部顶死)。 */
		if (linkid == 5)
		{
			int i;
			for (i = 0; i < MAX_SOCKETS_TCP; i++)
			{
				if (isconnected_network(i))
				{
					network_stop_thread(i);
				}
			}
			atsvr_cmd_rsp_ok();
			return;
		}

		if (linkid <= 6 && isconnected_network(linkid))
		{
			network_stop_thread(linkid);
			atsvr_cmd_rsp_ok();
		}
		else
		{
			atsvr_cmd_rsp_error();
		}
	}else{

		if (linkid <= 6 && isconnected_network(linkid))
		{
			network_stop_thread(linkid);
			atsvr_cmd_rsp_ok();
		}
		else
		{
			atsvr_cmd_rsp_error();
		}
	}

	return;
}

static void _atsvr_BIPMODE_handle(int argc, char * *argv)
{
	uint8			mode;
	int 			n	= 0;
	char			resultbuf[200];

	if (argc == 1)
	{
		n					= snprintf(resultbuf, sizeof(resultbuf), "+CIPMODE:%d\r\n",
			g_env_param.net_transmission_mode);
		n					+= snprintf(resultbuf + n, sizeof(resultbuf) -n, "%s", ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf, n);
	}
	else if (argc == 2)
	{
		mode				= atoi(argv[1]);
		g_env_param.net_transmission_mode = mode ? ATSVR_PASSTHROUGH_MODE: ATSVR_COMMON_MODE;

		if (g_env_param.sysstore)
		{
			write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
		}

		atsvr_cmd_rsp_ok();
	}
	else
	{
		atsvr_cmd_rsp_error();
		return;
	}

	return;
}

static void _atsvr_CIPMUX_Query_handle(int argc, char * *argv)
{
	int 			n	= 0;
	char			resultbuf[200];

	if (argc == 1)
	{
		n					= snprintf(resultbuf, sizeof(resultbuf), "+CIPMUX:%d\r\n", g_conmode);
		n					+= snprintf(resultbuf + n, sizeof(resultbuf) -n, "%s", ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf, n);
	}
}


static void _atsvr_CIPMUX_handle(int argc, char * *argv)
{
	if (argc == 2)
	{
		g_conmode			= atoi(argv[1]);
		if (g_conmode == 0 || g_conmode == 1)
		{
			atsvr_cmd_rsp_ok();
			return;
		}
	}
	else
	{
		atsvr_cmd_rsp_error();
		return;
	}
	return;
}

static void _atsvr_BIPSEND_handle(int argc, char * *argv)
{
	AT_FUNC_ENTRY;

	char			revbuf[1024];
	char			resultbuf[200];
	int 			revlen = 0;
	int 			len = 0;
	int 			linkid = 0;
	int 			n	= 0;

	if (argc == 1) //enter passthrough mode
	{
		ATSVRLOG("1argc:%d\r\n", argc);

		if (network_connected_num() == 1 && g_env_param.net_transmission_mode == ATSVR_PASSTHROUGH_MODE)
		{
			g_atsvr_status.network_transfer_mode = ATSVR_PASSTHROUGH_MODE;
			atsvr_cmd_rsp_passthrough();
		}
		else
		{
			atsvr_cmd_rsp_error();
			return;
		}

	}
	else if (argc == 2)
	{

		if (g_conmode == 0)
		{ //单连接

			len 				= atoi(argv[1]);

			/* ESP-AT: 单连接模式 AT+CIPSEND=<len> 对 UDP 链路同样有效。
			   原厂这里只处理 NETWORK_TCP, UDP 链路直接落 else 回 ERROR,
			   导致 AT+CIPSTART="UDP",... 建链成功后一个包都发不出去。 */
			/* ESP-AT 兼容修复: 原厂只放行 NETWORK_TCP, TLS 链路一律 ERROR ——
			   AT+CIPSTART="TLS" 连上了却一个包都发不出去。
			   network_tcp_send_msg() 内部是通过 at_network_mg[].netwrite 函数指针
			   分发的, 而 TLS 链路的 netwrite = network_tls_write, 所以它本来就通用。*/
		if (isconnected_network(0) && (network_check_connect_type(0, NETWORK_TCP)
									|| network_check_connect_type(0, NETWORK_TLS)))
			{
				g_atsvr_status.network_transfer_mode = ATSVR_PASSTHROUGH_REV_MODE;
				atsvr_cmd_rsp_passthrough();

				revlen				= atsvr_input_msg_get(revbuf, len);
				g_atsvr_status.network_transfer_mode = ATSVR_COMMON_MODE;

				if (network_tcp_send_msg(0, (unsigned char *) &revbuf[0], len) != len)
				{
					atsvr_output_msg("SEND ERROR\r\n", strlen("SEND ERROR\r\n"));
					return;
				}
				else
				{
					atsvr_output_msg("SEND OK\r\n", strlen("SEND OK\r\n"));
				}

				if (revlen > len)
				{
					int 			n	= 0;
					char			resultbuf[100];

					n					= snprintf(resultbuf, sizeof(resultbuf), "%s\r\n", &revbuf[len]);
					atsvr_output_msg(resultbuf, n);
					atsvr_cmd_rsp_busy();
				}

				return;
			}
			else if (isconnected_network(0) && network_check_connect_type(0, NETWORK_UDP))
			{
				g_atsvr_status.network_transfer_mode = ATSVR_PASSTHROUGH_REV_MODE;
				atsvr_cmd_rsp_passthrough();

				revlen				= atsvr_input_msg_get(revbuf, len);
				g_atsvr_status.network_transfer_mode = ATSVR_COMMON_MODE;

				if (network_udp_send_msg(0, (unsigned char *) &revbuf[0], len, NULL, 0) != len)
				{
					atsvr_output_msg("SEND ERROR\r\n", strlen("SEND ERROR\r\n"));
					return;
				}
				else
				{
					atsvr_output_msg("SEND OK\r\n", strlen("SEND OK\r\n"));
				}

				if (revlen > len)
				{
					int 			n	= 0;
					char			resultbuf[100];

					n					= snprintf(resultbuf, sizeof(resultbuf), "%s\r\n", &revbuf[len]);
					atsvr_output_msg(resultbuf, n);
					atsvr_cmd_rsp_busy();
				}

				return;
			}
			else
			{
				atsvr_cmd_rsp_error();
				return;
			}
		}
		else
		{

			atsvr_cmd_rsp_error();
			return;
		}

	}
	else if (argc == 3)
	{
		linkid				= atoi(argv[1]);
		len 				= atoi(argv[2]);

		if (isconnected_network(linkid))
		{
			g_atsvr_status.network_transfer_mode = ATSVR_PASSTHROUGH_REV_MODE;
			atsvr_cmd_rsp_passthrough();

			// revlen = atsvr_input_msg_get_block(revbuf,len);
			revlen				= atsvr_input_msg_get(revbuf, len);
			g_atsvr_status.network_transfer_mode = ATSVR_COMMON_MODE;

			/* 同上: 多连接分支也放行 TLS(CIPMUX=1 下的 AT+CIPSEND=<linkid>,<len>) */
		if(network_check_connect_type(linkid, NETWORK_TCP)
			|| network_check_connect_type(linkid, NETWORK_TLS))
			{
				if (network_tcp_send_msg(linkid, (unsigned char *) &revbuf[0], len) != len)
				{
					//atsvr_cmd_rsp_error();
					atsvr_output_msg("SEND ERROR\r\n", strlen("SEND ERROR\r\n"));
					return;
				}
				else
				{
					atsvr_output_msg("SEND OK\r\n", strlen("SEND OK\r\n"));
				}
			} 
			else if(network_check_connect_type(linkid, NETWORK_UDP))
			{
				if (network_udp_send_msg(linkid, (unsigned char *) &revbuf[0], len, NULL, 0) != len)
				{
					atsvr_output_msg("SEND ERROR\r\n", strlen("SEND ERROR\r\n"));
					return;
				}
				else
				{
					atsvr_output_msg("SEND OK\r\n", strlen("SEND OK\r\n"));
				}
			}

			if (revlen > len)
			{
				n					= snprintf(resultbuf, sizeof(resultbuf), "%s\r\n", &revbuf[len]);
				atsvr_output_msg(resultbuf, n);
				atsvr_cmd_rsp_busy();
			}

			return;
		}
		else
		{
			atsvr_cmd_rsp_error();
			return;
		}

	}
	else if (argc == 4)
	{

		if (g_conmode != 0)
		{
			atsvr_cmd_rsp_error();
			return;

		}

		len 				= atoi(argv[1]);
		char *			retmoteip = argv[2];
		int 			port = atoi(argv[3]);

		g_atsvr_status.network_transfer_mode = ATSVR_PASSTHROUGH_REV_MODE;
		atsvr_cmd_rsp_passthrough();

		revlen				= atsvr_input_msg_get(revbuf, len);
		g_atsvr_status.network_transfer_mode = ATSVR_COMMON_MODE;

		if (network_udp_send_msg(linkid, (unsigned char *) &revbuf[0], len, retmoteip, port) != len)
		{
			atsvr_output_msg("SEND ERROR\r\n", strlen("SEND ERROR\r\n"));
			return;
		}
		else
		{
			atsvr_output_msg("SEND OK\r\n", strlen("SEND OK\r\n"));
		}

		if (revlen > len)
		{

			n					= snprintf(resultbuf, sizeof(resultbuf), "%s\r\n", &revbuf[len]);
			atsvr_output_msg(resultbuf, n);
			atsvr_cmd_rsp_busy();
		}

	}
	else if (argc == 5)
	{
		if (g_conmode != 1)
		{
			atsvr_cmd_rsp_error();
			return;
		}

		linkid				= atoi(argv[1]);
		len 				= atoi(argv[2]);
		char *			retmoteip = argv[3];
		int 			port = atoi(argv[4]);

		g_atsvr_status.network_transfer_mode = ATSVR_PASSTHROUGH_REV_MODE;
		atsvr_cmd_rsp_passthrough();

		revlen				= atsvr_input_msg_get(revbuf, len);
		g_atsvr_status.network_transfer_mode = ATSVR_COMMON_MODE;

		if (network_udp_send_msg(linkid, (unsigned char *) &revbuf[0], len, retmoteip, port) != len)
		{
			atsvr_output_msg("SEND ERROR\r\n", strlen("SEND ERROR\r\n"));
			return;
		}
		else
		{
			atsvr_output_msg("SEND OK\r\n", strlen("SEND OK\r\n"));
		}

		if (revlen > len)
		{

			n					= snprintf(resultbuf, sizeof(resultbuf), "%s\r\n", &revbuf[len]);
			atsvr_output_msg(resultbuf, n);
			atsvr_cmd_rsp_busy();
		}

	}

	return;
}

/* AT+PING 的 ICMP Echo 实现在 atsvr_esp_compat.c（本项目自研）。
   刻意不复用 SDK 自带的 ping.c —— 那个文件是 GPL v2/v3 传染性组件，
   为了 ESP-AT 的 +PING:<ms> 语义去改它会把整个衍生作品拖成 GPL。 */
extern int atsvr_icmp_ping_once(const char *ip, int *out_ms, int timeout_ms);
static void _atsvr_PING_handle(int argc, char * *argv)
{
	char			hostip[16];
	char			resultbuf[64];
	int 			n	= 0;
	int 			ms	= -1;
	int 			ret = 0;

	if (argc != 2)
	{
		atsvr_cmd_rsp_error();
		return;
	}

	/* ESP-AT 语义: 可达回 +PING:<time>(毫秒), 不可达回 +PING:TIMEOUT, 两者都以 OK 结束。
	   原厂只回一个裸 OK, 上位机无法判断结果, 这里对齐 ESP-AT。 */
	if (atsvr_resolve_host(argv[1], hostip) == 0)
	{
		n		= snprintf(resultbuf, sizeof(resultbuf), "+PING:TIMEOUT\r\n%s", ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf, n);
		return;
	}

	ret 		= atsvr_icmp_ping_once(hostip, &ms, 3000);

	if (ret == 0 && ms >= 0)
	{
		n		= snprintf(resultbuf, sizeof(resultbuf), "+PING:%d\r\n%s", ms, ATSVR_CMD_RSP_SUCCEED);
	}
	else
	{
		n		= snprintf(resultbuf, sizeof(resultbuf), "+PING:TIMEOUT\r\n%s", ATSVR_CMD_RSP_SUCCEED);
	}

	atsvr_output_msg(resultbuf, n);

	return;
}


/* ---- ESP-AT AT+CIPSSLCCONF 兼容 -----------------------------------------
   ESP-AT 定义: AT+CIPSSLCCONF=<auth_mode>[,<pki_number>,<ca_number>]
     auth_mode 0 = 不认证(不校验服务端证书)  <-- 默认, 也是 ESP-AT 官方支持的模式
     auth_mode 1 = ESP-AT 提供客户端证书给服务端校验
     auth_mode 2 = 客户端载入 CA 校验服务端证书
     auth_mode 3 = 相互认证
   CA 在 ESP-AT 里也是编译期烧进 flash 分区的, 运行时不提供下发命令(AT+SYSMFG
   是 ESP32 专属扩展)。本移植同样不在运行时装载 CA, 且刻意**不改动 ENV_PARAM
   布局**(flash env 向后兼容优先), 因此只用函数级静态保存, 复位后回到默认 0。 */
static int s_ssl_auth_mode = 0;      /* 0 = 不认证 */

int atsvr_get_ssl_auth_mode(void)
{
	return s_ssl_auth_mode;
}

static void _atsvr_at_BIPSSLCONF_Query_command(int argc, char **argv)
{
	char	resultbuf[80];
	int		n	= 0;

	if (argc != 1)
	{
		atsvr_cmd_rsp_error();
		return;
	}

	/* 本移植没有可配置的 PKI/CA 索引, 固定回 0(与 AT+CIPSSLCCONF=0 一致)。*/
	n= snprintf(resultbuf, sizeof(resultbuf), "+CIPSSLCCONF:%d,0,0\r\n%s",
			s_ssl_auth_mode, ATSVR_CMD_RSP_SUCCEED);
	atsvr_output_msg(resultbuf, n);
}

static void _atsvr_at_BIPSSLCONF_command(int argc, char **argv)
{
	int	auth	= 0;
	int	pki		= 0;
	int	ca		= 0;

	/* ESP-AT 里 pki_number / ca_number 是可选的(auth_mode=0 时无需填)。*/
	if (argc != 2 && argc != 3 && argc != 4)
	{
		atsvr_cmd_rsp_error();
		return;
	}

	auth = atoi(argv[1]);
	if (argc >= 3)
	{
		pki	= atoi(argv[2]);
	}
	if (argc >= 4)
	{
		ca	= atoi(argv[3]);
	}

	if (auth < 0 || auth > 3 || pki < 0 || ca < 0)
	{
		ATSVRLOG("CIPSSLCCONF: bad args\r\n");
		atsvr_cmd_rsp_error();
		return;
	}

	/* 必须在建连之前生效: 改完直接下一次 CIPSTART 生效, 与 ESP-AT 一致。*/
	s_ssl_auth_mode	= auth;
	atsvr_cmd_rsp_ok();
}


void _atsvr_at_BIPPSK_Query_command(int argc, char * *argv)
{
	int 			n	= 0;
	char			resultbuf[200];

	if (argc == 1)
	{
		n					= snprintf(resultbuf, sizeof(resultbuf), "+CIPSSLCPSK:%d,%s,%s\r\n",
			g_env_param.pskinfo.linkid, g_env_param.pskinfo.psk, g_env_param.pskinfo.hint);
		n					+= snprintf(resultbuf + n, sizeof(resultbuf) -n, "%s", ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf, n);
	}
	else
	{
		atsvr_cmd_rsp_error();
		return;
	}
}


void _atsvr_at_BIPPSK_command(int argc, char * *argv)
{
	ATSVRLOG("entr _atsvr_at_BIPPSK_command,argc:%d\r\n",argc);

	if (argc == 4)
	{
		int 			linkid = atoi(argv[1]);

		if (linkid > 5)
		{
			atsvr_cmd_rsp_error();
			return;
		}

		g_env_param.pskinfo.linkid = linkid;

		if (strlen(argv[2]) > 0)
		{
			memset(&g_env_param.pskinfo.psk,0,MAX_SIZE_OF_DEVICE_SECRET +1);
			strcpy(g_env_param.pskinfo.psk, argv[2]);
			ATSVRLOG("hint:%s\r\n", g_env_param.pskinfo.psk);
		}
		else
		{
			atsvr_cmd_rsp_error();
			return;
		}

		if (strlen(argv[3]) > 0)
		{
			memset(&g_env_param.pskinfo.hint,0,MAX_SIZE_OF_DEVICE_SECRET +1);
			strcpy(g_env_param.pskinfo.hint, argv[3]);
			ATSVRLOG("hint:%s\r\n", g_env_param.pskinfo.hint);
		}
		else
		{
			atsvr_cmd_rsp_error();
			return;
		}

		if (g_env_param.sysstore)
		{
			write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
		}

		atsvr_cmd_rsp_ok();
	}
	else
	{
		atsvr_cmd_rsp_error();
		return;
	}
}

void _atsvr_at_BIPSNTPCFG_Query_command(int argc, char * *argv)
{
	int 			n	= 0;
	char			resultbuf[200];

	if (argc == 1)
	{
		n					= snprintf(resultbuf, sizeof(resultbuf), "+CIPSNTPCFG:%d,%d,%s\r\n",
			g_env_param.ntpinfo.enable, g_env_param.ntpinfo.timezone, g_env_param.ntpinfo.hostname);
		n					+= snprintf(resultbuf + n, sizeof(resultbuf) -n, "%s", ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf, n);
	}
	else
	{

		atsvr_cmd_rsp_error();
		return;
	}
}

void _atsvr_at_BIPSNTPCFG_command(int argc, char * *argv)
{
	if (argc >= 4)
	{
		g_env_param.ntpinfo.enable = atoi(argv[1]);

		if (g_env_param.ntpinfo.enable == 0)
		{

			if (g_env_param.sysstore)
			{
				write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
			}

			atsvr_cmd_rsp_ok();
			return;
		}

		g_env_param.ntpinfo.timezone = strtol(argv[2], NULL, 10);

		strcpy(g_env_param.ntpinfo.hostname, argv[3]);

		if (g_env_param.sysstore)
		{
			write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
		}

		ATSVRLOG("eable:%d,timezone:%d,hostname:%s\r\n", g_env_param.ntpinfo.enable, g_env_param.ntpinfo.timezone,
			g_env_param.ntpinfo.hostname);

		ntp_info_update(g_env_param.ntpinfo.timezone, g_env_param.ntpinfo.hostname);

		atsvr_cmd_rsp_ok();
		return;

	}
	else
	{
		atsvr_cmd_rsp_error();
		return;
	}

}

void _atsvr_at_BIPSNTPTIME_command(int argc, char * *argv)
{
	if (argc == 1)
	{
		int 			n	= 0;
		char			resultbuf[200];
		time_t			now;

		struct tm * time_now;
		sddev_control(SOFT_RTC_DEVICE_NAME, RT_DEVICE_CTRL_RTC_GET_TIME, &now);
		time_now			= localtime(&now);

		n					= snprintf(resultbuf, sizeof(resultbuf), "+CIPSNTPTIME:%d-%d-%d %d-%d-%d\r\n",
			time_now->tm_year + 1900, time_now->tm_mon + 1, time_now->tm_mday, time_now->tm_hour, time_now->tm_min,
			time_now->tm_sec);
		n					+= snprintf(resultbuf + n, sizeof(resultbuf) -n, "%s", ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf, n);
		return;
	}
	else
	{

		atsvr_cmd_rsp_error();
		return;
	}
}

extern void *zalloc(size_t size);
int get_domainip(const char * hname, char * hostip)
{
	const size_t	hstbuflen = 1024;
	char *			tmphstbuf = NULL;

	if (hostip == NULL)
		return 0;

	tmphstbuf			= (char *) zalloc(sizeof(char) *hstbuflen);

	if (tmphstbuf == NULL)
		return 0;

	struct hostent * pent = lwip_gethostbyname(hname);

	if (pent == NULL || pent->h_addr == NULL)
	{
		free(tmphstbuf);
		return 0;
	}
	strcpy(hostip, inet_ntoa(* ((struct in_addr *) pent->h_addr)));
	free(tmphstbuf);
	return 1;
}

void _atsvr__atsvr_at_BIPDOMAIN_command(int argc, char * *argv)
{
	if (argc >= 2)
	{
		char			remoteip[16];

		if (get_domainip(argv[1], remoteip))
		{
			int 			n	= 0;
			char			resultbuf[200];

			if (judge_the_string_is_ipv4_string(remoteip) == -1)
			{
				atsvr_cmd_rsp_error();
				return;
			}

			n					= snprintf(resultbuf, sizeof(resultbuf), "+CIPDOMAIN:\"%s\"\r\n", remoteip);
			n					+= snprintf(resultbuf + n, sizeof(resultbuf) -n, "%s", ATSVR_CMD_RSP_SUCCEED);
			atsvr_output_msg(resultbuf, n);
			return;
		}
	}
	else
	{
		atsvr_cmd_rsp_error();
		return;
	}

	/* 解析失败也必须给应答, 否则上位机会一直等 (ESP-AT 行为: 回 ERROR) */
	atsvr_cmd_rsp_error();
}

void _atsvr__atsvr_at_BIPDNS_command(int argc, char * *argv)
{
	int 			enable = 0;

	if (argc == 2)
	{

		enable				= atoi(argv[1]);

		if (enable == 0)
		{
			g_env_param.dnsinfo.enable = 0;
			strcpy(g_env_param.dnsinfo.dns1, "208.67.222.222");
			atsvr_cmd_rsp_ok();
		}
		else
		{

			atsvr_cmd_rsp_error();
			return;
		}

	}
	else if (argc >= 3)
	{
		ip_addr_t		dns_array[3];
		int 			n	= 0;
		enable				= atoi(argv[1]);

		if (enable == 1)
		{
			if (judge_the_string_is_ipv4_string(argv[2]) == 0)
			{
				strcpy(g_env_param.dnsinfo.dns1, argv[2]);
				ipaddr_aton(g_env_param.dnsinfo.dns1, &dns_array[0]);
				dns_setserver(n, &dns_array[0]);
				n++;
			}
			else
			{
				atsvr_cmd_rsp_error();
				return;
			}
		}

		if (argc == 4)
		{

			if (judge_the_string_is_ipv4_string(argv[3]) == 0)
			{

				strcpy(g_env_param.dnsinfo.dns2, argv[3]);
				ipaddr_aton(g_env_param.dnsinfo.dns2, &dns_array[1]);
				dns_setserver(n, &dns_array[1]);
				n++;
			}
			else
			{
				atsvr_cmd_rsp_error();
				return;
			}
		}


		if (argc == 5)
		{

			if (judge_the_string_is_ipv4_string(argv[4]) == 0)
			{
				strcpy(g_env_param.dnsinfo.dns3, argv[4]);
				ipaddr_aton(g_env_param.dnsinfo.dns2, &dns_array[2]);
				dns_setserver(n, &dns_array[2]);
				n++;
			}
			else
			{
				atsvr_cmd_rsp_error();
				return;
			}
		}

		if (g_env_param.sysstore)
			write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);

		atsvr_cmd_rsp_ok();
	}
}

#ifdef CFG_SUPPORT_ESP8266
void atsvr_savetranslink_command(int argc, char **argv)
{
	if(argc != 2 && argc != 4 && argc != 5){
			atsvr_cmd_rsp_error();
			return;
	}
	uint8 mode = 0;
	char* remote_host = NULL;
	uint32 remote_port = 0;
	char* type = NULL;

	mode = atoi(argv[1]);

	/* ESP-AT 兼容修复: ESP-AT 允许 AT+SAVETRANSLINK=<mode> 单参数形式,
	   mode=0 即"关闭保存透传"。原厂强制 argc==4|5, 于是 "=0" 直接回 ERROR,
	   上位机没法单独关掉这个功能, 只能硬塞一对无意义的 host/port。
	   这里补上单参数分支: mode=0 -> 清 autotransinfo + 回到普通模式;
	   mode!=0 因缺 host/port 无意义 -> ERROR。 */
	if(argc == 2){
		if(mode == 0){
			g_env_param.net_transmission_mode = ATSVR_COMMON_MODE;
			g_env_param.autotransinfo.enable = 0;
			write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
			atsvr_cmd_rsp_ok();
		}else{
			atsvr_cmd_rsp_error();
		}
		return;
	}

	remote_host = argv[2];
	remote_port = atoi(argv[3]);
	if(argc == 4){
		type = "TCP";
	}else if(argc == 5){
		if((strcmp(argv[4], "TCP") == 0) || (strcmp(argv[4], "tcp") == 0))
		{
			type = "TCP";
		}else if((strcmp(argv[4], "UDP") == 0) || (strcmp(argv[4], "udp") == 0))
		{
			type = "UDP";
		}else{
			atsvr_cmd_rsp_error();
			return;
		}
	}

	if(mode == 1){
		g_env_param.wifimode.mode = 1;
		g_env_param.wifimode.autoconnect = 1;
		g_env_param.net_transmission_mode = ATSVR_PASSTHROUGH_MODE;
		g_env_param.autotransinfo.enable = 1;
		strcpy(g_env_param.autotransinfo.type, type);
		strcpy(g_env_param.autotransinfo.remote_host, remote_host);
		g_env_param.autotransinfo.remote_port = remote_port;
		write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
		atsvr_cmd_rsp_ok();
	} else if(mode == 0){
		g_env_param.net_transmission_mode = ATSVR_COMMON_MODE;
		g_env_param.autotransinfo.enable = 0;
		write_env_to_flash(TAG_SYSSTORE_OFFSET, sizeof(ENV_PARAM), (uint8 *) &g_env_param);
		atsvr_cmd_rsp_ok();
	} else{
		atsvr_cmd_rsp_error();
	}
	
	return;
}

void atsvr_cipserver_command(int argc, char **argv)
{
	if(argc != 2 && argc != 3 && argc != 4){
		atsvr_cmd_rsp_error();
		return;
	}
	uint8 mode = 0;
	uint32 param2 = 0;
	NETWORK_TYPE type = NETWORK_TCP;

	mode = atoi(argv[1]);

	/* 守卫只应限制"开启"服务端:
	     - CIPMUX=0 时不能开 (ESP-AT 同)
	   "关闭"(mode=0) 必须永远可用, 否则服务端一旦有客户端就连不上了。
	   ESP-AT 兼容修复: 服务端使用 link5, link0~4 被客户端占用时开服务端
	   完全合法 —— 原守卫 isconnected_network(0) 会在"客户端已接入 +
	   TCP 建连超时(对端已 accept 但本端报 ERROR)留下半开连接"后把
	   UDP/TCP 服务端一并拒掉。link5 占用时下方已有 stop+重开逻辑。 */
	if(mode != 0 && !g_conmode){
		atsvr_cmd_rsp_error();
		return;
	}
	if(mode == 1){
		if(argc == 2){
			param2 = 333;
		} else if(argc == 3){
			param2 = atoi(argv[2]);
		}else if(argc == 4){
			param2 = atoi(argv[2]);
			if((strcmp(argv[3], "UDP") == 0) || (strcmp(argv[3], "udp") == 0))
			{
				type = NETWORK_UDP;
			}
		}
		pm_socket_info_t rcvmsg = {0};
		rcvmsg.linkid = 5;
		if(isconnected_network(5))
		{
			network_stop_thread(5);
			/* 等接收线程退出并释放端口, 否则新 listen 会失败 */
			rtos_thread_msleep(800);
		}
		rcvmsg.type = type;
		rcvmsg.localport = param2;
		rcvmsg.linktype = 1;
		rtos_push_to_queue(&network_msg_que, &rcvmsg, BEKEN_NO_WAIT);
	} else if(mode == 0){
		for(int linkid = 0; linkid <= 5; linkid++){
			if (isconnected_network(linkid))
			{
				network_stop_thread(linkid);
			}
		}
		/* 给接收线程时间退出并关 socket, 再回 OK */
		rtos_thread_msleep(800);
		atsvr_cmd_rsp_ok();
	} else{
		atsvr_cmd_rsp_error();
	}
}
#endif

const struct _atsvr_command _atsvc_netcmds_table[] =
{
	_ATSVR_CMD_HADLER("AT+CIPSTATUS?", "AT+CIPSTATUS?", _atsvr_BIPSTATUS_handle),
	_ATSVR_CMD_HADLER("AT+CIPSTART", "AT+CIPSTART", _atsvr_BIPSTART_handle),
	_ATSVR_CMD_HADLER("AT+CIPCLOSE", "AT+CIPCLOSE", _atsvr_BIPCLOSE_handle),
	_ATSVR_CMD_HADLER("AT+CIPMODE", "AT+CIPMODE=<mode>", _atsvr_BIPMODE_handle),
	_ATSVR_CMD_HADLER("AT+CIPMUX?", "AT+CIPMUX?", _atsvr_CIPMUX_Query_handle),
	_ATSVR_CMD_HADLER("AT+CIPMUX", "AT+CIPMUX=<mode>", _atsvr_CIPMUX_handle),
	_ATSVR_CMD_HADLER("AT+CIPSEND", "AT+CIPSEND=[<linkid>,]<length>,[<remotehost>,<remoteport>]",
		_atsvr_BIPSEND_handle),
	_ATSVR_CMD_HADLER("AT+PING", "AT+PING=<host>", _atsvr_PING_handle),
	_ATSVR_CMD_HADLER("AT+CIPSSLCPSK", "AT+CIPSSLCPSK=<linkid>,<psk_key>,<hint>", _atsvr_at_BIPPSK_command),
	_ATSVR_CMD_HADLER("AT+CIPSSLCPSK?", "AT+CIPSSLCPSK?", _atsvr_at_BIPPSK_Query_command),
	_ATSVR_CMD_HADLER("AT+CIPSSLCCONF?", "AT+CIPSSLCCONF?", _atsvr_at_BIPSSLCONF_Query_command),
	_ATSVR_CMD_HADLER("AT+CIPSSLCCONF", "AT+CIPSSLCCONF=<auth_mode>[,<pki_number>,<ca_number>]",
		_atsvr_at_BIPSSLCONF_command),
	_ATSVR_CMD_HADLER("AT+CIPSNTPCFG?", "AT+CIPSNTPCFG?", _atsvr_at_BIPSNTPCFG_Query_command),
	_ATSVR_CMD_HADLER("AT+CIPSNTPCFG", "AT+CIPSNTPCFG=<enable>,<timezone>,<SNTPserver1>,<SNTPserver2>,<SNTPserver3>,",
		_atsvr_at_BIPSNTPCFG_command),
	_ATSVR_CMD_HADLER("AT+CIPSNTPTIME?", "AT+CIPSNTPTIME?", _atsvr_at_BIPSNTPTIME_command),
	_ATSVR_CMD_HADLER("AT+CIPDOMAIN", "AT+CIPDOMAIN=<domain>[,<ip network>]", _atsvr__atsvr_at_BIPDOMAIN_command),
	_ATSVR_CMD_HADLER("AT+CIPDNS", "AT+CIPDNS=<enable>[,<dns1>,<dns2>,<dns3>]", _atsvr__atsvr_at_BIPDNS_command),
};

#ifdef CFG_SUPPORT_ESP8266
const struct _atsvr_command _atsvc_netcmds_table_esp8266[] = {
		ATSVR_CMD_HADLER("AT+SAVETRANSLINK","AT+SAVETRANSLINK=<mode>,<\"remote host\">,<remote port>[,<\"type>\"]",atsvr_savetranslink_command),
		ATSVR_CMD_HADLER("AT+CIPSERVER","AT+CIPSERVER=<mode>[,<param2>][,<\"type\">]",atsvr_cipserver_command),
};
#endif

void atsvr_network_init()
{
	atsvr_register_commands(_atsvc_netcmds_table, sizeof(_atsvc_netcmds_table) / sizeof(struct _atsvr_command));
#ifdef CFG_SUPPORT_ESP8266
	atsvr_register_commands(_atsvc_netcmds_table_esp8266, sizeof(_atsvc_netcmds_table_esp8266) / sizeof(struct _atsvr_command));
#endif
	create_network_task();
}
#endif
