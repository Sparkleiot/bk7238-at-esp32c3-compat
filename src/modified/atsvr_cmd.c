#include "atsvr_cmd.h"
#include "at_server.h"
#include "atsvr_wlan.h"
#include "atsvr_misc.h"
#include "string.h"
#include "stdio.h"
#include "stdlib.h"
#include "typedef.h"
#include "atsvr_comm.h"
#include "wlan_defs_pub.h"
#include "common.h"
#include "wlan_ui_pub.h"
#include "lwip/ip_addr.h"
#if CFG_USE_NETWORKING

#define MAC_LEN_IN_BYTE  6

/* ---- ESP32-C3 / ESP-AT 兼容层 (atsvr_esp_compat.c) ---- */
extern void atsvr_esp_compat_init(void);
extern void atsvr_cwjap_query_command(int argc, char **argv);
/* 按实际命令名生成应答标签（AT+CIPSTA?_CUR/_DEF 共用同一处理函数时需要） */
extern const char *atsvr_esp_tag(int argc, char **argv, char *buf, int bufsz, const char *fallback);

int copy_str2mac(unsigned char*mac,char*str)
{
	unsigned char hi_byte,lo_byte;
	char t_str; 
	for(int i = 0; i< MAC_LEN_IN_BYTE; i++)
	{
		t_str =  str[i*3];
		switch(t_str)
		{
		case '0'...'9':
			hi_byte = (unsigned char)atoi(&t_str);
			break;
		case 'a'...'f':
			hi_byte = 0xa + (t_str-'a');
			break;
		case 'A'...'F':
			hi_byte = 0xa + (t_str-'A');
			break;
		default:
			return -1;
		}
		
		t_str =  str[i*3+1];
		switch(t_str)
		{
		case '0'...'9':
			lo_byte = (unsigned char)atoi(&t_str);
			break;
		case 'a'...'f':
			lo_byte = 0xa + (t_str-'a');
			break;
		case 'A'...'F':
			lo_byte = 0xa + (t_str-'A');
			break;
		default:
			return -1;
		}

		mac[i] =(hi_byte << 4) | lo_byte; 
		
	}

	return 0;
}

extern int wifi_set_mac_address(char *mac);

static void atsvr_set_station_mac(int argc, char **argv)
{
	if(argc == 2){

	unsigned char mac[7];
	if(copy_str2mac(mac,argv[1])==-1)
	{
		ATSVRLOG("argv[1]:%s\r\n",argv[1]);
		atsvr_cmd_rsp_error();
		return;
	}
	ATSVRLOG("argv[1]:%s,mac:%02x:%02x:%02x:%02x:%02x:%02x\r\n",argv[1],mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);
	wifi_set_mac_address((char*)mac);
	atsvr_cmd_rsp_ok();

	}
	else{
	atsvr_cmd_rsp_error();
	}
}

static void atsvr_get_station_mac(int argc, char **argv)
{
	if(argc == 1){
		unsigned char mac[MAC_LEN_IN_BYTE];
		int n = 0;
		char resultbuf[200];
		char tagbuf[24];
		const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CIPSTAMAC");

		wlan_get_station_mac_address((char*)mac);

		n = snprintf(resultbuf,sizeof(resultbuf),"+%s:\"%02x:%02x:%02x:%02x:%02x:%02x\"\r\n",tag,mac[0],
				mac[1],mac[2],mac[3],mac[4],mac[5]);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf,n);
		return;
	}
	else{
		atsvr_cmd_rsp_error();
	}
}

void atsvr_set_station_dhcp_query(int argc, char **argv)
{
	if(argc == 1){
		int n = 0;
		char resultbuf[200];
		char tagbuf[24];
		const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWDHCP");
		n = snprintf(resultbuf,sizeof(resultbuf),"+%s:%d\r\n",tag,(g_env_param.stainfo.dhcp | (g_env_param.apinfo.dhcp<<1)));//(g_env_param.stainfo.dhcp & 0x01) | 0x2);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf,n);
	}
	else{

		atsvr_cmd_rsp_error();
		return;
	}

	return;
}

void atsvr_set_station_dhcp(int argc, char **argv)
{
	int operate,mode;

	if(argc != 3){
		atsvr_cmd_rsp_error();
		return;
	}

	operate =  atoi(argv[1]);
	mode =  atoi(argv[2]);
	if(operate > 1)
	{
		operate = 1;
	}

	/* ESP-AT 兼容修复: mode 编码改为 0=SoftAP, 1=Station, 2=Station+SoftAP。
	 * 原厂是 1=sta, 2=ap, 3=both, 0=ERROR —— 与 ESP-AT 文档不符。 */
	switch(mode)
	{
		case 0:	//softap
			g_env_param.apinfo.dhcp = operate;
		break;
		case 1:	//station
			g_env_param.stainfo.dhcp = operate;
		break;
		case 2:	//station+softap
			g_env_param.stainfo.dhcp = operate;
			g_env_param.apinfo.dhcp = operate;
		break;
		default :
			atsvr_cmd_rsp_error();
			return;
	}
	if(g_env_param.sysstore)
			write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(g_env_param),(uint8*)&g_env_param);
	atsvr_cmd_rsp_ok();
	return;
}

static void atsvr_station_ssid_pwd(int argc, char **argv)
{
	char *my_ssid=NULL;
	char *connect_key=NULL;
	int updateflag = 0;
	if(argc == 1){
		wlan_start_station_connect(g_env_param.stainfo.con_ssid,g_env_param.stainfo.con_key);
		atsvr_cmd_rsp_ok();
		return;
	}
	else if(argc == 2){
		my_ssid = argv[1];
		connect_key = "OPEN";
	}else if(argc == 3){
		my_ssid = argv[1];
		connect_key = argv[2];
	}else if(argc > 3){
		my_ssid = argv[1];
		connect_key = argv[2];
	}

	if(wlan_start_station_connect(my_ssid, connect_key) == 0){
		if(strcmp(g_env_param.stainfo.con_ssid, my_ssid)!=0){
		strcpy(g_env_param.stainfo.con_ssid,my_ssid);
		updateflag =1;
		}

	if(strcmp(g_env_param.stainfo.con_key, connect_key)!=0){

		strcpy(g_env_param.stainfo.con_key ,connect_key);
		updateflag =1;
	}

	if(updateflag)
	{
		write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(g_env_param),(uint8*)&g_env_param);
	}
	atsvr_cmd_rsp_ok();

	}else{
		atsvr_cmd_rsp_error();
	}

	return;
}

static void atsvr_station_stop(int argc, char **argv)
{
	if(argc != 1){
		atsvr_cmd_rsp_error();
		return;
	}

	if(wlan_stop_station() == 0){
		atsvr_cmd_rsp_ok();
	}else{
		atsvr_cmd_rsp_error();
	}

	return;
}

static void atsvr_station_static_ip(int argc, char **argv)
{
	/* ESP-AT 兼容修复: gateway/netmask 可选 —— AT+CIPSTA=<"ip">[,<"gateway">[,<"netmask">]] */
	if(argc < 2 || argc > 4){
		atsvr_cmd_rsp_error();
		return;
	}
	char *ip = argv[1];
	char *gate = (argc >= 3) ? argv[2] : g_env_param.stainfo.sta_gate;
	char *mask = (argc >= 4) ? argv[3] : g_env_param.stainfo.sta_mask;

	if(judge_the_string_is_ipv4_string(ip) != 0){
		atsvr_cmd_rsp_error();
		ATSVRLOG("[atsvr]ip:%s error\r\n",ip);
		return;
	}
	if(judge_the_string_is_ipv4_string(gate) != 0){
		atsvr_cmd_rsp_error();
		ATSVRLOG("[atsvr]gate:%s error\r\n",gate);
		return;
	}
	if(judge_the_string_is_ipv4_string(mask) != 0){
		atsvr_cmd_rsp_error();
		ATSVRLOG("[atsvr]mask:%s error\r\n",mask);
		return;
	}

	if(wlan_set_station_static_ip(ip, mask,gate) == 0){
		strcpy(g_env_param.stainfo.sta_local_ip,ip);
		strcpy(g_env_param.stainfo.sta_mask,mask);
		strcpy(g_env_param.stainfo.sta_gate,gate);
		if(g_env_param.sysstore)
		{
			write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(g_env_param),(uint8*)&g_env_param);
		}

		IPStatusTypedef ipstatus;

		strcpy(ipstatus.ip,g_env_param.stainfo.sta_local_ip);
		strcpy(ipstatus.mask,g_env_param.stainfo.sta_mask);
		strcpy(ipstatus.gate,g_env_param.stainfo.sta_gate);
		strcpy(ipstatus.dns,g_env_param.dnsinfo.dns1);
		ipstatus.dhcp = g_env_param.stainfo.dhcp;
		bk_wlan_set_ip_status(&ipstatus,BK_STATION);

		atsvr_cmd_rsp_ok();
	}else{
		atsvr_cmd_rsp_error();
	}
}

void atsvr_get_station_status(int argc, char **argv)
{
	if(argc != 1){
		atsvr_cmd_rsp_error();
		return;
	}
	LinkStatusTypeDef stalinkstatus;
	memset(&stalinkstatus,0,sizeof(LinkStatusTypeDef));
	bk_wlan_get_link_status(&stalinkstatus);
	IPStatusTypedef ipStatus;
	bk_wlan_get_ip_status(&ipStatus, BK_STATION);

	int n = 0;
	char resultbuf[1024];
	n = snprintf(resultbuf,sizeof(resultbuf),"+STAST:%s,dhcp=%d, ip=%s, gate=%s, mask=%s,mac=" MACSTR ",RSSI:%d,ssid:%s,channel:%d,security:%d\r\n",stalinkstatus.conn_state? "connected":"disconnected",ipStatus.dhcp, ipStatus.ip, ipStatus.gate,
				ipStatus.mask, MAC2STR((unsigned char*)ipStatus.mac),stalinkstatus.wifi_strength,stalinkstatus.ssid,stalinkstatus.channel,stalinkstatus.security);
	n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
	atsvr_output_msg(resultbuf,n);

	return;
}

void atsvr_get_information_ip(int argc, char **argv)
{
	if(argc != 1){
		atsvr_cmd_rsp_error();
		return;
	}
	LinkStatusTypeDef stalinkstatus;
	memset(&stalinkstatus,0,sizeof(LinkStatusTypeDef));
	bk_wlan_get_link_status(&stalinkstatus);
	IPStatusTypedef ipStatus;
	bk_wlan_get_ip_status(&ipStatus, BK_STATION);

	int n = 0;
	char resultbuf[1024];
	char tagbuf[24];
	const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CIPSTA");
	n = snprintf(resultbuf,sizeof(resultbuf),"+%s:ip:\"%s\"\r\n",tag,ipStatus.ip);
	n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"+%s:gateway:\"%s\"\r\n",tag,ipStatus.gate);
	n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"+%s:netmask:\"%s\"\r\n",tag,ipStatus.mask);
	n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
	atsvr_output_msg(resultbuf,n);

	return;
}

void atsvr_wlan_set_ap_proto_cmd(int argc, char **argv)
{
	if((argc != 1) && (argc != 2)){
		atsvr_cmd_rsp_error();
		return;
	}

	if(argc == 1)
	{
				char output[100];
				int n;
				n = snprintf(output,100,"+WLAPPROTO:%d\r\n",g_env_param.apinfo.proto);
				n += snprintf(output+n,100 - n,ATSVR_CMD_RSP_SUCCEED);
				atsvr_output_msg(output,n);
	}
	else if(argc == 2){

		g_env_param.apinfo.proto = atoi(argv[1]);

		wlan_softap_start(g_env_param.apinfo.ap_ssid, g_env_param.apinfo.ap_key,g_env_param.apinfo.channel,g_env_param.apinfo.proto,g_env_param.apinfo.hidden);

		if(g_env_param.sysstore)
			write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(ENV_PARAM),(uint8*)&g_env_param);
	}

	atsvr_cmd_rsp_ok();
	return;
}

void atsvr_wlan_scan_cmd(int argc, char **argv)
{
	if((argc != 1) && (argc != 2)){
		atsvr_cmd_rsp_error();
		return;
	}
	char *ssid = NULL;

	if(argc == 2){
		ssid = argv[1];
	}
	if(wlan_scan_start(ssid) != 0){
		atsvr_cmd_rsp_error();
		return;
	}
	set_atsvr_work_state(ATSVR_WK_DONE);
	atsvr_cmd_rsp_ok();
	return;
}

static void atsvr_softap_start(int argc, char **argv)
{
	if(argc < 5)
	{
		atsvr_cmd_rsp_error();
		return;
	}
	char *my_ssid;
	char *connect_key;
	int channel =0;
	int encryp=0;
	int hidden = 0 ;

	my_ssid = argv[1];
	connect_key = argv[2];
	channel= atoi(argv[3]);
	if(channel >14) {
		atsvr_cmd_rsp_error();
		return;
	}
	encryp=atoi(argv[4]);
	if(argc >= 6) {

	}

	if(argc >= 7) {

		hidden = atoi(argv[6]);
	}

	/* ESP-AT 兼容修复: AT+CWSAP 在任何模式下都应 OK —— 存配置, 待 AP 模式
	 * 激活时生效(切 CWMODE=2/3 或下次上电)。原厂在 STA 模式直接 ERROR,
	 * 导致 ESP-AT 流程"先 CWSAP 再 CWMODE=3"永远失败。 */
	if(g_env_param.wifimode.mode < 2){
		strcpy(g_env_param.apinfo.ap_ssid,my_ssid);
		strcpy(g_env_param.apinfo.ap_key,connect_key);
		g_env_param.apinfo.channel=channel;
		g_env_param.apinfo.ap_enc=encryp;
		g_env_param.apinfo.hidden=hidden;
		if(g_env_param.sysstore)
			write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(ENV_PARAM),(uint8*)&g_env_param);
		atsvr_cmd_rsp_ok();
		return;
	}

	/* ESP-AT CWSAP <ecn> -> BK sec type; don't pass the stale apinfo.proto. */
	ATSVRLOG("CWSAP argc=%d ssid=%s ch=%d ecn=%d -> bksec=%d\r\n",
	         argc, my_ssid, channel, encryp, atsvr_ecn_to_bk_sec(encryp));
	if(wlan_softap_start(my_ssid, connect_key,channel,atsvr_ecn_to_bk_sec(encryp),hidden) == 0){

			/* Always store the new AP config. The old code only persisted it
			 * when ssid/key changed, so an ecn-only change (e.g. turning an
			 * open AP into WPA2) was dropped and AT+CWSAP? reported a stale
			 * ecn forever. */
			strcpy(g_env_param.apinfo.ap_ssid,my_ssid);
			strcpy(g_env_param.apinfo.ap_key,connect_key);
			g_env_param.apinfo.channel=channel;
			g_env_param.apinfo.ap_enc=encryp;
			g_env_param.apinfo.hidden=hidden;
			if(g_env_param.sysstore)
				write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(ENV_PARAM),(uint8*)&g_env_param);
			atsvr_cmd_rsp_ok();
		}else{
			atsvr_cmd_rsp_error();
		}

	return;
}

static void atsvr_softap_stop(int argc, char **argv)
{
	if(argc != 1){
		atsvr_cmd_rsp_error();
		return;
	}

	if(wlan_stop_softap() == 0){
		set_atsvr_work_state(ATSVR_WK_DONE);
		atsvr_cmd_rsp_ok();
	}else{
		set_atsvr_work_state(ATSVR_WK_DONE);
		atsvr_cmd_rsp_error();
	}

	return;
}

static void atsvr_softap_query(int argc, char **argv)
{
	char resultbuf[160];
	char tagbuf[24];
	int n;
	uint8 ecn = g_env_param.apinfo.ap_enc;
	const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWSAP");

	/* vendor default ap_enc=8 is not a valid ESP-AT ecn (0-4);
	 * the radio actually broadcasts WPA2_PSK in that case */
	if (ecn > 4)
	{
		ecn = 4;
	}

	n = snprintf(resultbuf, sizeof(resultbuf),
	             "+%s:\"%s\",\"%s\",%d,%d\r\n",
	             tag,
	             g_env_param.apinfo.ap_ssid,
	             g_env_param.apinfo.ap_key,
	             g_env_param.apinfo.channel,
	             ecn);
	n += snprintf(resultbuf + n, sizeof(resultbuf) - n,
	             "%s", ATSVR_CMD_RSP_SUCCEED);
	atsvr_output_msg(resultbuf, n);
}

static void atsvr_softap_query_static_ip(int argc, char **argv)
{
	if(argc ==1){
		int n = 0;
		char resultbuf[256];
		char tagbuf[24];
		const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CIPAP");
		n = snprintf(resultbuf,sizeof(resultbuf),"+%s:ip:\"%s\"\r\n",tag,g_env_param.apinfo.ap_local_ip);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"+%s:gateway:\"%s\"\r\n",tag,g_env_param.apinfo.ap_gate);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"+%s:netmask:\"%s\"\r\n",tag,g_env_param.apinfo.ap_mask);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf,n);
	}
	else{
		atsvr_cmd_rsp_error();
	}
	return;
}

static void atsvr_softap_static_ip(int argc, char **argv)
{
	/* ESP-AT 兼容修复:
	 * 1) 参数顺序改为 <"ip">,<"gateway">,<"netmask"> —— 原厂是
	 *    (ip, mask, gate), 与 ESP-AT 正好相反, 导致按 ESP-AT 文档发
	 *    AT+CIPAP="ip","gw","mask" 时网关被写成掩码。
	 * 2) gateway/netmask 为可选参数(与 ESP-AT 一致): 只给 ip 时保持
	 *    原有 gateway/netmask 不变。 */
	if (argc < 2 || argc > 4) {
			atsvr_cmd_rsp_error();
			return;
	}

		char *ip = argv[1];
		char *gate = (argc >= 3) ? argv[2] : g_env_param.apinfo.ap_gate;
		char *mask = (argc >= 4) ? argv[3] : g_env_param.apinfo.ap_mask;

		if(judge_the_string_is_ipv4_string(ip) != 0){
			atsvr_cmd_rsp_error();
			ATSVRLOG("[atsvr]ip:%s error\r\n",ip);
			return;
		}
		if(judge_the_string_is_ipv4_string(mask) != 0){
			atsvr_cmd_rsp_error();
			ATSVRLOG("[atsvr]mask:%s error\r\n",mask);
			return;
		}
		if(judge_the_string_is_ipv4_string(gate) != 0){
			atsvr_cmd_rsp_error();
			ATSVRLOG("[atsvr]gate:%s error\r\n",gate);
			return;
		}


		if(wlan_set_softap_static_ip(ip, mask,gate) == 0){
			strcpy(g_env_param.apinfo.ap_local_ip,ip);
			strcpy(g_env_param.apinfo.ap_mask,mask);
			strcpy(g_env_param.apinfo.ap_gate,gate);

			wlan_stop_softap();
			wlan_softap_start(g_env_param.apinfo.ap_ssid, g_env_param.apinfo.ap_key,g_env_param.apinfo.channel,atsvr_ecn_to_bk_sec(g_env_param.apinfo.ap_enc),g_env_param.apinfo.hidden);

			if(g_env_param.sysstore)
				write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(ENV_PARAM),(uint8*)&g_env_param);
			atsvr_cmd_rsp_ok();
		}else{
			atsvr_cmd_rsp_error();
		}
	return;
}

/* ---------------- ESP-AT 兼容新增: AT+CWDHCPS ----------------
 * ESP-AT 语义:
 *   AT+CWDHCPS=<enable>[,<lease time>[,<start IP>[,<end IP>]]]
 *     enable: 0 关 SoftAP DHCP server, 1 开
 *     lease time: 分钟(默认 2880), start/end: IP 字符串
 *   AT+CWDHCPS? -> +CWDHCPS:<lease>,<start>,<end>\r\nOK
 * range 是运行期配置(ESP-AT 的 _CUR 语义), enable 项会写入 env。 */
static uint32_t g_ap_dhcp_lease = 2880;      /* minutes */
static uint32_t g_ap_dhcp_range_start = 0;   /* host order; 0 = 按 AP 子网默认 .2~.101 */
static uint32_t g_ap_dhcp_range_end = 0;

extern void dhcp_server_set_range(uint32_t start_host, uint32_t end_host);

static int atsvr_parse_ip_u32(const char *s, uint32_t *out)
{
	unsigned a,b,c,d;
	if(!s || sscanf(s, "%u.%u.%u.%u", &a,&b,&c,&d) != 4)
		return -1;
	if(a > 255 || b > 255 || c > 255 || d > 255)
		return -1;
	*out = (a << 24) | (b << 16) | (c << 8) | d;
	return 0;
}

static void atsvr_ip_to_str(uint32_t ip, char *buf, int len)
{
	snprintf(buf, len, "%u.%u.%u.%u",
	         (unsigned)((ip >> 24) & 0xff), (unsigned)((ip >> 16) & 0xff),
	         (unsigned)((ip >> 8) & 0xff), (unsigned)(ip & 0xff));
}

static void atsvr_softap_dhcps(int argc, char **argv)
{
	if(argc <= 1){
		/* query: +CWDHCPS:<lease>,"<start>","<end>" */
		uint32_t s = g_ap_dhcp_range_start, e = g_ap_dhcp_range_end;
		if(!s || !e){
			uint32_t apip = 0, apmask = 0;
			atsvr_parse_ip_u32(g_env_param.apinfo.ap_local_ip, &apip);
			atsvr_parse_ip_u32(g_env_param.apinfo.ap_mask, &apmask);
			/* ESP-AT 默认段: AP 子网内 .2 ~ .101 */
			s = (apip & apmask) | 2;
			e = (apip & apmask) | 101;
		}
		char sbuf[16], ebuf[16];
		char tagbuf[24];
		char resultbuf[128];
		const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWDHCPS");
		atsvr_ip_to_str(s, sbuf, sizeof(sbuf));
		atsvr_ip_to_str(e, ebuf, sizeof(ebuf));
		int n = snprintf(resultbuf,sizeof(resultbuf),"+%s:%d,\"%s\",\"%s\"\r\n",
		                  tag, (int)g_ap_dhcp_lease, sbuf, ebuf);
		n += snprintf(resultbuf+n,sizeof(resultbuf)-n,"%s",ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf,n);
		return;
	}

	int enable = atoi(argv[1]);
	if(enable == 0){
		g_env_param.apinfo.dhcp = 0;
	}else if(enable == 1){
		g_env_param.apinfo.dhcp = 1;
		if(argc >= 3)
			g_ap_dhcp_lease = (uint32_t)atoi(argv[2]);
		if(argc >= 5){
			uint32_t s, e, apip = 0, apmask = 0;
			if(atsvr_parse_ip_u32(argv[3], &s) != 0 ||
			   atsvr_parse_ip_u32(argv[4], &e) != 0 ||
			   s > e){
				atsvr_cmd_rsp_error();
				return;
			}
			/* 必须与 AP IP 同网段 */
			atsvr_parse_ip_u32(g_env_param.apinfo.ap_local_ip, &apip);
			atsvr_parse_ip_u32(g_env_param.apinfo.ap_mask, &apmask);
			if(((s ^ apip) & apmask) || ((e ^ apip) & apmask)){
				atsvr_cmd_rsp_error();
				return;
			}
			g_ap_dhcp_range_start = s;
			g_ap_dhcp_range_end = e;
		}
	}else{
		atsvr_cmd_rsp_error();
		return;
	}

	/* 交给 dhcpd(下一次 SoftAP 起来时生效), 并在 AP 模式下热重启使其立即生效 */
	dhcp_server_set_range(g_ap_dhcp_range_start, g_ap_dhcp_range_end);
	if(g_env_param.sysstore)
		write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(g_env_param),(uint8*)&g_env_param);
	if(g_env_param.wifimode.mode & 0x2){
		wlan_stop_softap();
		wlan_softap_start(g_env_param.apinfo.ap_ssid, g_env_param.apinfo.ap_key,
		                  g_env_param.apinfo.channel,
		                  atsvr_ecn_to_bk_sec(g_env_param.apinfo.ap_enc),
		                  g_env_param.apinfo.hidden);
	}
	atsvr_cmd_rsp_ok();
	return;
}

void atsvr_get_softap_status(int argc, char **argv)
{
	if(argc != 1){
		atsvr_cmd_rsp_error();
		return;
	}

	int n = 0;
	char resultbuf[1024];
	wlan_ap_stas_t stas;
	memset(&stas,0,sizeof(wlan_ap_stas_t));

	wlan_ap_sta_info(&stas);

	bk_printf("connnected sta num:%d\r\n",stas.num);

	for(int index=0;index<stas.num;index++)
	{
		/* ESP-AT 格式: +CWLIF:<ip addr>,<mac>
		 * 注意 MACSTR 宏自带尾随空格，这里显式写格式以免污染应答 */
		n += snprintf(resultbuf+n,sizeof(resultbuf)-n,"+CWLIF:%s,%02x:%02x:%02x:%02x:%02x:%02x\r\n",
			ipaddr_ntoa((const ip_addr_t *)&stas.sta[index].ipaddr),
			stas.sta[index].addr[0],stas.sta[index].addr[1],stas.sta[index].addr[2],
			stas.sta[index].addr[3],stas.sta[index].addr[4],stas.sta[index].addr[5]);
	}
	if(n>0)
	{
		atsvr_output_msg(resultbuf,n);
	}
	set_atsvr_work_state(ATSVR_WK_DONE);
	atsvr_cmd_rsp_ok();
	return;
}

void atsvr_wifimode_command(int argc, char **argv)
{
	uint8  mode;
	uint8  lastmode;
	int n = 0;
	char resultbuf[200];
	uint8 autoconnect;
	char tagbuf[24];
	const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWMODE");
	if(argc == 1){
		n = snprintf(resultbuf,sizeof(resultbuf),"+%s:%d\r\n",tag,g_env_param.wifimode.mode);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf,n);
		return;
	}
	else if(argc == 2){
		mode = atoi(argv[1]);
		/* ESP-AT compat fix: capture lastmode BEFORE overwriting
		 * g_env_param.wifimode.mode, otherwise update_wifi_action()
		 * always receives identical modes and does nothing. */
		lastmode = g_env_param.wifimode.mode;
		g_env_param.wifimode.mode=mode;
		if(g_env_param.sysstore)
			write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(ENV_PARAM),(uint8*)&g_env_param);
		atsvr_cmd_rsp_ok();
	}
	else if(argc == 3)
	{
		mode = atoi(argv[1]);
		autoconnect = atoi(argv[2]);
		lastmode = g_env_param.wifimode.mode;
		g_env_param.wifimode.mode =mode;
		g_env_param.wifimode.autoconnect = autoconnect;
		if(g_env_param.sysstore) {
			write_env_to_flash(TAG_SYSSTORE_OFFSET,sizeof(ENV_PARAM),(uint8*)&g_env_param);
		}
		atsvr_cmd_rsp_ok();
	}
	else{
		atsvr_cmd_rsp_error();
		return;
	}

	update_wifi_action(lastmode, mode);
	return;
}

void atsvr_wifimode_query_command(int argc, char **argv)
{
	int n = 0;
	char resultbuf[200];
	char tagbuf[24];
	const char *tag = atsvr_esp_tag(argc, argv, tagbuf, sizeof(tagbuf), "CWMODE");
	if(argc == 1){
		n = snprintf(resultbuf,sizeof(resultbuf),"+%s:%d\r\n",tag,g_env_param.wifimode.mode);
		n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
		atsvr_output_msg(resultbuf,n);
		return;
	}

	return;
}

void atsvr_startsmartconfig_command(int argc, char **argv)
{
	atsvr_cmd_rsp_ok();
	return;
}

#ifdef CFG_SUPPORT_ESP8266
void atsvr_cwlapopt_command(int argc, char **argv)
{
	atsvr_cmd_rsp_ok();
	return;
}

void atsvr_cwlap_command(int argc, char **argv)
{
	if((argc != 1) && (argc != 2)){
			atsvr_cmd_rsp_error();
			return;
	}
	char *ssid = NULL;

	if(argc == 2){
			ssid = argv[1];
	}
	if(wlan_scan_start(ssid) != 0){
			atsvr_cmd_rsp_error();
			return;
	}
	set_atsvr_work_state(ATSVR_WK_DONE);
	atsvr_cmd_rsp_ok();
	return;
}

void atsvr_cifsr_command(int argc, char **argv)
{
	int n = 0;
	char resultbuf[1024];	
	IPStatusTypedef ipStatus;	
	unsigned char mac[MAC_LEN_IN_BYTE];

	if(argc != 1){
		atsvr_cmd_rsp_error();
		return;
	}

	bk_wlan_get_ip_status(&ipStatus, BK_STATION);
	wlan_get_station_mac_address((char*)mac);

	n = snprintf(resultbuf,sizeof(resultbuf),"+CIFSR:STAIP,\"%s\"\r\n",ipStatus.ip);
	n += snprintf(resultbuf+n,sizeof(resultbuf)- n,"+CIFSR:STAMAC,\"%02x:%02x:%02x:%02x:%02x:%02x\"\r\n",mac[0],
				mac[1],mac[2],mac[3],mac[4],mac[5]);
	n += snprintf(resultbuf+n,sizeof(resultbuf) - n,"%s",ATSVR_CMD_RSP_SUCCEED);
	atsvr_output_msg(resultbuf,n);

	return;
}

void atsvr_cwreconncfg_command(int argc, char **argv)
{
	if(argc != 2){
			atsvr_cmd_rsp_error();
			return;
	}
	//uint32 interval_second = 0;
	//uint32 repeat_count = 0;

	//interval_second = atoi(argv[1]);
	//repeat_count = atoi(argv[1]);
	
	atsvr_cmd_rsp_ok();
	return;
}
#endif

const struct _atsvr_command atsvc_cmds_table[] = {
	ATSVR_CMD_HADLER("AT+CWMODE","AT+CWMODE",atsvr_wifimode_command),
	ATSVR_CMD_HADLER("AT+CWMODE?","AT+CWMODE?",atsvr_wifimode_query_command),

	ATSVR_CMD_HADLER("AT+CIPSTAMAC?","AT+CIPSTAMAC?",atsvr_get_station_mac),
	ATSVR_CMD_HADLER("AT+CIPSTAMAC","AT+CIPSTAMAC=<\"mac\">",atsvr_set_station_mac),

	ATSVR_CMD_HADLER("AT+CWSAP","AT+CWSAP=<\"ssid\">,<\"pwd\">,<channel>,<ecn>,<max conn>,<hidden>",atsvr_softap_start),
	ATSVR_CMD_HADLER("AT+CWSAP?","AT+CWSAP?",atsvr_softap_query),
	ATSVR_CMD_HADLER("AT+CWSAP_CUR?","AT+CWSAP_CUR?",atsvr_softap_query),
	ATSVR_CMD_HADLER("AT+CWSAP_DEF?","AT+CWSAP_DEF?",atsvr_softap_query),
	ATSVR_CMD_HADLER("AT+CWSAP_CUR","AT+CWSAP_CUR=<\"ssid\">,<\"pwd\">,<channel>,<ecn>",atsvr_softap_start),
	ATSVR_CMD_HADLER("AT+CWSAP_DEF","AT+CWSAP_DEF=<\"ssid\">,<\"pwd\">,<channel>,<ecn>",atsvr_softap_start),
	ATSVR_CMD_HADLER("AT+CWQIF","AT+CWQIF",atsvr_softap_stop),    //�Ͽ���AP������

	ATSVR_CMD_HADLER("AT+CIPAP?","AT+CIPAP?",atsvr_softap_query_static_ip),
	ATSVR_CMD_HADLER("AT+CIPAP","AT+CIPAP=<\"ip\">[,<\"gateway\">[,<\"netmask\">]]",atsvr_softap_static_ip),
	ATSVR_CMD_HADLER("AT+CWLIF","AT+CWLIF?",atsvr_get_softap_status),

	//ATSVR_CMD_HADLER("AT+WLAPPROTO","AT+WLAPPROTO",atsvr_wlan_set_ap_proto_cmd),
	ATSVR_CMD_HADLER("AT+WSCAN","AT+WSCAN",atsvr_wlan_scan_cmd),

	ATSVR_CMD_HADLER("AT+CWDHCP?","AT+CWDHCP?",atsvr_set_station_dhcp_query),
	ATSVR_CMD_HADLER("AT+CWDHCP","AT+CWDHCP=<enable>,<mode>",atsvr_set_station_dhcp),
	ATSVR_CMD_HADLER("AT+CWJAP","AT+CWJAP=[<SSID>],[<PWD>][,<bssid>][,<pci_en>][,<reconn_interval>][,<listen_interval>][,scan_mode][,jap_timeout][,<pmf>]",atsvr_station_ssid_pwd),
	ATSVR_CMD_HADLER("AT+CWJAP?","AT+CWJAP?",atsvr_cwjap_query_command),
	ATSVR_CMD_HADLER("AT+CWQAP","AT+CWQAP",atsvr_station_stop),
	ATSVR_CMD_HADLER("AT+CIPSTA?","AT+CIPSTA?",atsvr_get_information_ip),
	ATSVR_CMD_HADLER("AT+CIPSTA","AT+CIPSTA=<\"ip\">[,<\"gateway\">[,<\"netmask\">]]",atsvr_station_static_ip),
	ATSVR_CMD_HADLER("AT+STAST?","AT+STAST?",atsvr_get_station_status),

	/* ---- ESP-AT 兼容别名: _CUR(当前值) / _DEF(默认值, 落 flash) ----
	 * ESP-AT 中 _CUR 与 _DEF 的区别仅在于是否写入 flash;
	 * 本 SDK 已由 SYSSTORE 开关统一控制持久化, 故两者复用同一处理函数即可,
	 * 目的只是让上位机的 AT+CWMODE_CUR? / AT+CIPSTA_DEF? 等命令不再返回 ERROR。 */
	ATSVR_CMD_HADLER("AT+CWMODE_CUR?","AT+CWMODE_CUR?",atsvr_wifimode_query_command),
	ATSVR_CMD_HADLER("AT+CWMODE_CUR","AT+CWMODE_CUR=<mode>",atsvr_wifimode_command),
	ATSVR_CMD_HADLER("AT+CWMODE_DEF?","AT+CWMODE_DEF?",atsvr_wifimode_query_command),
	ATSVR_CMD_HADLER("AT+CWMODE_DEF","AT+CWMODE_DEF=<mode>",atsvr_wifimode_command),
	ATSVR_CMD_HADLER("AT+CWDHCP_CUR?","AT+CWDHCP_CUR?",atsvr_set_station_dhcp_query),
	ATSVR_CMD_HADLER("AT+CWDHCP_CUR","AT+CWDHCP_CUR=<enable>,<mode>",atsvr_set_station_dhcp),
	ATSVR_CMD_HADLER("AT+CWDHCP_DEF?","AT+CWDHCP_DEF?",atsvr_set_station_dhcp_query),
	ATSVR_CMD_HADLER("AT+CWDHCP_DEF","AT+CWDHCP_DEF=<enable>,<mode>",atsvr_set_station_dhcp),
	ATSVR_CMD_HADLER("AT+CWDHCPS?","AT+CWDHCPS?",atsvr_softap_dhcps),
	ATSVR_CMD_HADLER("AT+CWDHCPS","AT+CWDHCPS=<enable>[,<lease>[,\"<start>\"[,\"<end>\"]]]",atsvr_softap_dhcps),
	ATSVR_CMD_HADLER("AT+CWDHCPS_CUR?","AT+CWDHCPS_CUR?",atsvr_softap_dhcps),
	ATSVR_CMD_HADLER("AT+CWDHCPS_CUR","AT+CWDHCPS_CUR=<enable>[,<lease>[,\"<start>\"[,\"<end>\"]]]",atsvr_softap_dhcps),
	ATSVR_CMD_HADLER("AT+CWDHCPS_DEF?","AT+CWDHCPS_DEF?",atsvr_softap_dhcps),
	ATSVR_CMD_HADLER("AT+CWDHCPS_DEF","AT+CWDHCPS_DEF=<enable>[,<lease>[,\"<start>\"[,\"<end>\"]]]",atsvr_softap_dhcps),
	ATSVR_CMD_HADLER("AT+CIPSTA_CUR?","AT+CIPSTA_CUR?",atsvr_get_information_ip),
	ATSVR_CMD_HADLER("AT+CIPSTA_CUR","AT+CIPSTA_CUR=<\"ip\">,<\"mask\">,<\"gate\">",atsvr_station_static_ip),
	ATSVR_CMD_HADLER("AT+CIPSTA_DEF?","AT+CIPSTA_DEF?",atsvr_get_information_ip),
	ATSVR_CMD_HADLER("AT+CIPSTA_DEF","AT+CIPSTA_DEF=<\"ip\">,<\"mask\">,<\"gate\">",atsvr_station_static_ip),
	ATSVR_CMD_HADLER("AT+CIPSTAMAC_CUR?","AT+CIPSTAMAC_CUR?",atsvr_get_station_mac),
	ATSVR_CMD_HADLER("AT+CIPSTAMAC_DEF?","AT+CIPSTAMAC_DEF?",atsvr_get_station_mac),
	ATSVR_CMD_HADLER("AT+CIPAP_CUR?","AT+CIPAP_CUR?",atsvr_softap_query_static_ip),
	ATSVR_CMD_HADLER("AT+CIPAP_DEF?","AT+CIPAP_DEF?",atsvr_softap_query_static_ip),
	ATSVR_CMD_HADLER("AT+CWJAP_CUR","AT+CWJAP_CUR=[<ssid>],[<pwd>]",atsvr_station_ssid_pwd),
	ATSVR_CMD_HADLER("AT+CWJAP_DEF","AT+CWJAP_DEF=[<ssid>],[<pwd>]",atsvr_station_ssid_pwd),
};

#ifdef CFG_SUPPORT_ESP8266
const struct _atsvr_command atsvc_cmds_table_esp8266[] = {
        ATSVR_CMD_HADLER("AT+CWLAPOPT","AT+CWLAPOPT=<\"sort\">,<\"mask\">",atsvr_cwlapopt_command),
        ATSVR_CMD_HADLER("AT+CWLAP","AT+CWLAP=[<SSID>],[,<mac>][,<channel>][,<scan_type>][,<scan_time_min>][,<scan_time_max>]",atsvr_cwlap_command),
        ATSVR_CMD_HADLER("AT+CIFSR","AT+CIFSR",atsvr_cifsr_command),
		ATSVR_CMD_HADLER("AT+CWRECONNCFG","AT+CWRECONNCFG=<interval_second>,<repeat_count>",atsvr_cwreconncfg_command),
};
#endif

void atsvr_cmd_init(void)
{
	atsvr_register_commands(atsvc_cmds_table, sizeof(atsvc_cmds_table) / sizeof(struct _atsvr_command));
#ifdef CFG_SUPPORT_ESP8266
	atsvr_register_commands(atsvc_cmds_table_esp8266, sizeof(atsvc_cmds_table_esp8266) / sizeof(struct _atsvr_command));
#endif
	/* ESP32-C3 / ESP-AT 兼容层: 补齐缺失命令（新增文件 atsvr_esp_compat.c） */
	atsvr_esp_compat_init();
	//atsvr_extern_cmd_init();

	atsvr_wlan_init();
}

void __weak__ atsvr_extern_cmd_init(void)
{

}
#endif
