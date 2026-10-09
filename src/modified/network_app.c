#include "sockets.h"
#include "_atsvr_func.h"
#include "_at_server.h"
#include "atsvr_comm.h"
#include "string.h"
#include "sockets.h"
#include "mem_pub.h"
#include "BkDriverFlash.h"
#include "sys.h"
#include "manual_ps_pub.h"
#include "atsvr_misc.h"
#include "atsvr_port.h"
#include "atsvr_net_cmd.h"
#include "network_interface.h"
#include "atsvr_param_check.h"
#include "atsvr_error.h"
#include "network_app.h"
#include "at_server.h"
#include "atsvr_wlan.h"
#include "wlan_ui_pub.h"
//#include "lwip/netdb.h"
#if CFG_USE_TCPUDP
beken_queue_t network_msg_que;

/* 定义在 atsvr_net_cmd.c, 0:单连接(CIPMUX=0) 1:多连接(CIPMUX=1) */
extern int atsvr_get_conmode(void);

#define MAX_ITEM_COUNT      (15)
#define MAX_SOCKET_LINK     (6)
#define UNKNOW_LINK_IDX     0xff
ATNetwork at_network_mg[6];
ThreadParams g_thread_manage[MAX_THREAD_NUM];

int g_thread_index = 0;

int network_creat_thread(beken_thread_function_t       callback, IN void* para, char *threadname)
{
    /* 原厂缺陷: 线程槽只增不减 —— 只用 g_thread_manage[g_thread_index++],
       MAX_THREAD_NUM=10, 约 10 条连接(含每次 accept)后槽位耗尽,
       且继续递增会越界写内存, 之后任何网络连接都建不起来。
       修复: 优先复用已退出线程的空槽(thread_id==0, 由
       network_thread_slot_release() 在线程退出时清零)。 */
    int slot = -1;
    int i;
    for (i = 0; i < MAX_THREAD_NUM; i++) {
        if (g_thread_manage[i].thread_id == 0) { slot = i; break; }
    }
    if (slot < 0) {
        ATSVRLOG("no free thread slot\r\n");
        return kGeneralErr;
    }

    strcpy(g_thread_manage[slot].thread_name,threadname);
    g_thread_manage[slot].user_arg =  para;
    g_thread_manage[slot].stack_size = 4096;
    g_thread_manage[slot].priority = THD_APPLICATION_PRIORITY;
    g_thread_manage[slot].thread_func = callback;

    if(HAL_ThreadCreate( &g_thread_manage[slot]) ==ATSVR_RET_SUCCESS){
        g_thread_index++;
        return kNoErr;
    }

    return kGeneralErr;
}

/* 接收线程退出时释放自己的线程槽 —— 与 network_creat_thread 的空槽复用配套 */
static void network_thread_slot_release(void)
{
    beken_thread_t self = (beken_thread_t)rtos_get_current_thread();
    int i;
    for (i = 0; i < MAX_THREAD_NUM; i++) {
        if (g_thread_manage[i].thread_id != 0 &&
            g_thread_manage[i].thread_id == self) {
            g_thread_manage[i].thread_id = 0;
            break;
        }
    }
}

int network_stop_thread(int linkid)
{
    char linkname[64];
    int i = 0, w;
    sprintf(linkname,"NET_LINK%d",linkid);

    for( i = 0; i < MAX_THREAD_NUM; i++)
    {
        if((strcmp(g_thread_manage[i].thread_name,linkname)==0) && (g_thread_manage[i].thread_id !=0)) {
            //rtos_thread_join(g_thread_manage[i].pthreadID);
            at_network_mg[linkid].threadrunflag= FALSE;
            // rtos_delete_thread(g_thread_manage[i].thread_id);
            ATSVRLOG("\r\nDELETE THREAD SUCCESS(%s) \r\n",linkname);
            break;
        }
    }
    if(i >= MAX_THREAD_NUM)
        return kGeneralErr;

    /* ESP-AT 兼容修复(#13 真因): CIPCLOSE 必须是"同步"的。
       原来这里只把 threadrunflag 清 FALSE 就返回, 而接收线程还阻塞在
       netread/select 里, 最多要等 1s 超时才回到循环顶部退出; 它退出时才
       close(fd) 并把 at_network_mg[linkid].handle 清 0。
       这段时间里 isconnected_network(linkid)==1, 于是上位机紧接着的
       AT+CIPSTART=<同一 linkid> 会命中 _atsvr_BIPSTART_handle 里的
       "if (linkid > 5 || isconnected_network(linkid)) -> linkid error" 直接回 ERROR。
       实测: CIPCLOSE 后 ≤0.5s 内 CIPSTART 必 ERROR, ≥0.8s 才 OK —— 而 ESP-AT
       允许立即 CIPCLOSE->CIPSTART, 所以这里是真缺陷(不是端口占用)。
       修法: 等线程槽真正释放再返回。槽释放发生在 close(fd)+handle=0 之后
       (见 network_datarev_thread 尾部: 先 disconnect/handle=0, 再 slot_release),
       所以等到槽没了, handle 必然已归 0。 */
    for (w = 0; w < 250; w++) {          /* 上限 250×10ms = 2.5s */
        int busy = 0;
        for (i = 0; i < MAX_THREAD_NUM; i++) {
            if (g_thread_manage[i].thread_id != 0 &&
                strcmp(g_thread_manage[i].thread_name, linkname) == 0) { busy = 1; break; }
        }
        if (!busy && at_network_mg[linkid].handle == 0) {
            break;
        }
        rtos_thread_msleep(10);
    }
    if (w >= 250) {
        ATSVRLOG("warn: wait %s exit timeout, handle=%d\r\n",
                 linkname, (int)at_network_mg[linkid].handle);
    }

    return kNoErr;
}

int network_connected_num()
{
    int connectcnt = 0;
    for(int i = 0; i< MAX_SOCKET_LINK; i++ )
    {
        if(at_network_mg[i].handle > 0){
            connectcnt++;
        }
    }

    return connectcnt;
}

int network_get_idle_linkid()
{
    for(int i = 0; i < MAX_SOCKET_LINK; i++ )
    {
        if(at_network_mg[i].handle <= 0){
            return i;
        }
    }    

    return UNKNOW_LINK_IDX;
}


int network_find_linkid_by_handle(int handle)
{
    for(int i = 0; i< MAX_SOCKET_LINK; i++ )
    {
        if(at_network_mg[i].handle == handle){
            return i;
        }
    }

    return -1;
}

int isconnected_network(int linkid)
{
   return at_network_mg[linkid].handle ? 1:0;
}

int network_check_connect_type(int linkid,NETWORK_TYPE contype)
{
     return (at_network_mg[linkid].type == contype) ? 1: 0;
}

/*
 * 逐条打印已建立的连接, 供 AT+CIPSTATUS / AT+CIPSTATE 复用。
 *   +<tag>:<link ID>,<"type">,<"remote IP">,<remote port>,<local port>,<tetype>
 *   <tetype>: 0=client, 1=server
 */
static int network_dump_links(const char *tag)
{
    int n = 0;
    char resultbuf[256];

    for (int i = 0; i < MAX_SOCKET_LINK; i++) {
        if (isconnected_network(i)) {
            n = snprintf(resultbuf, sizeof(resultbuf),
                         "+%s:%d,\"%s\",\"%s\",%d,%d,%d\r\n",
                         tag, i,
                         network_check_connect_type(i, NETWORK_TCP) ? "TCP" : "UDP",
                         at_network_mg[i].host,
                         at_network_mg[i].port,
                         at_network_mg[i].localport,
                         at_network_mg[i].is_server ? 1 : 0);
            atsvr_output_msg(resultbuf, n);
        }
    }
    return kNoErr;
}

/* AT+CIPSTATE —— 新版 ESP-AT 的逐连接查询命令 */
int network_cipstate_dump(void)
{
    return network_dump_links("CIPSTATE");
}

/*
 * AT+CIPSTATUS 响应 —— 对齐经典 ESP-AT (ESP32-C3) 格式:
 *   STATUS:<stat>
 *   +CIPSTATUS:<link ID>,<"type">,<"remote IP">,<remote port>,<local port>,<tetype>
 *   <stat>: 0=未连接 1=已连AP无IP 2=已获取IP 3=已建立TCP/UDP连接 4=连接全部关闭 5=WiFi未连接
 */
int network_link_status()
{
    int n = 0;
    char resultbuf[64];
    LinkStatusTypeDef link;
    IPStatusTypedef   ipStatus;
    int stat = 5;

    memset(&link, 0, sizeof(link));
    bk_wlan_get_link_status(&link);
    memset(&ipStatus, 0, sizeof(ipStatus));
    bk_wlan_get_ip_status(&ipStatus, BK_STATION);

    if (link.conn_state == 0) {
        stat = 5;                                   /* WiFi 未连接 */
    } else if (strcmp(ipStatus.ip, "0.0.0.0") == 0) {
        stat = 1;                                   /* 已连 AP 但未取到 IP */
    } else {
        stat = network_connected_num() ? 3 : 2;     /* 3: 已建立连接 2: 已取到 IP */
    }

    n = snprintf(resultbuf, sizeof(resultbuf), "STATUS:%d\r\n", stat);
    atsvr_output_msg(resultbuf, n);

    return network_dump_links("CIPSTATUS");
}

int network_passthrough_send_msg(unsigned char* sendbuff,int len)
{
    unsigned int writelen = 0;
    for(int i = 0; i< MAX_SOCKET_LINK; i++)
    {
        if(at_network_mg[i].handle > 0){
            ATSVRLOG("network_passthrough_send_msg len:%d\n",len);
            /* ESP-AT 透传发送也要按连接类型分派:
               UDP socket 走 netwrite(TCP connect 语义)发不出去, 必须走 UDP 发送路径 */
            if (at_network_mg[i].type == NETWORK_UDP)
            {
                writelen = network_udp_send_msg(i, sendbuff, len, NULL, 0);
            }
            else
            {
                at_network_mg[i].netwrite(&at_network_mg[i],sendbuff,len,3000,&writelen);
            }
            break;
        }
    }

    return writelen;
}

int network_tcp_send_msg(int linkid, unsigned char* sendbuff,int len)
{
    unsigned int writelen = 0;

    if(at_network_mg[linkid].handle >= 0) {
        sendbuff[len]='\0';
        at_network_mg[linkid].netwrite(&at_network_mg[linkid],sendbuff,len,3000,&writelen);
        ATSVRLOG("linkid:%d,send :%s,writelen:%d,len=%d\n",linkid,sendbuff,writelen,len);
    }

    return writelen;
}

int network_udp_send_msg(int linkid, unsigned char* sendbuff,int len,char*remoteip, int port)
{
    unsigned int writelen = 0;

    if(at_network_mg[linkid].handle >= 0){
        sendbuff[len]='\0';
        if(!remoteip || !port)
        {
           remoteip =  at_network_mg[linkid].host;
           port = at_network_mg[linkid].port;
        }
        writelen = HAL_UDP_WriteTo(at_network_mg[linkid].handle, sendbuff, len, remoteip, port);
        ATSVRLOG("linkid:%d,send :%s\n",linkid,sendbuff);
    }

    return writelen;
}

#if 1
int network_set_keep_alive(uintptr_t socket_fd,int keepalive)
{
    int opt = 1;
    int ret = 0;
    int fd = socket_fd - LWIP_SOCKET_FD_SHIFT;

    /*****close keepalive******/
    if(keepalive == 0){
        opt = 1;
        return kNoErr;
    }

    // open tcp keepalive
    ret = setsockopt(fd, SOL_SOCKET, SO_KEEPALIVE, &opt, sizeof(int));
    if(ret < 0)
    {
        return kGeneralErr;
    }

    opt = keepalive;
    ret = setsockopt(fd, IPPROTO_TCP, TCP_KEEPIDLE, &opt, sizeof(int));
    if(ret < 0)
    {
        return kGeneralErr;
    }

    opt = 1;  // 1s second for intval
    ret = setsockopt(fd, IPPROTO_TCP, TCP_KEEPINTVL, &opt, sizeof(int));
    if(ret < 0)
    {
        return kGeneralErr;
    }

    opt = 3;  // 3 times
    ret = setsockopt(fd, IPPROTO_TCP, TCP_KEEPCNT, &opt, sizeof(int));
    if(ret < 0)
    {
        return kGeneralErr;
    }

    return kNoErr;
}
#endif

extern int wlan_get_sta_localip(char * localip);
extern int wlan_get_ap_localip(char * localip);
/* ESP-AT AT+CIPSSLCCONF 的 auth_mode(0=不认证/默认, 2|3=校验服务端)。
   实现见 atsvr_net_cmd.c, 放函数级静态, 不进 flash env(避免改动 ENV_PARAM 布局)。*/
extern int atsvr_get_ssl_auth_mode(void);

void setup_msg_network(ATNetwork *pATNetwork , pm_socket_info_t msg)
{
    POINTER_SANITY_CHECK_RTN(pATNetwork);
    strncpy((char *)pATNetwork->host,msg.remoteip,16);
    pATNetwork->port = msg.port;
    pATNetwork->type = msg.type;
    pATNetwork->is_server = 0;
    pATNetwork->keepalive = msg.keepalive;
    pATNetwork->udpmode = msg.udpmode;

    /* ESP-AT 兼容修复: 原来这整段是被注释掉的, ssl_connect_params 保持全零 ——
       ca_crt=NULL / psk=NULL / psk_length=0 / timeout_ms=0, 再叠加
       HAL_TLS_mbedtls.c 里硬编码的 VERIFY_REQUIRED, 导致 AT+CIPSTART="TLS"
       握手必然失败(能力缺口)。这里按 ESP-AT 语义显式装配:
         auth_mode  由 AT+CIPSSLCCONF 设置(默认 0 = 不认证), 见 atsvr_net_cmd.c
         timeout_ms 握手超时兜底 10s(原厂 0 不可控)
         psk         仅当用户用 AT+CIPSSLCPSK 配过才使用
         ca_crt      本移植暂不支持运行时装载 CA(与 ESP-AT 一致: CA 在编译期
                     烧进 flash 分区), 因此恒为 NULL; auth_mode=2/3 时才需要。
         psk         **刻意保持 NULL**。原厂注释掉的代码想读 env 里的全局 PSK,
                     但那是"残留"语义: env 里的 PSK 是历史 AT+CIPSSLCPSK 测试留下的,
                     把它自动套到每一次 TLS 连接上会直接打死证书模式 ——
                     mbedtls_ssl_conf_psk 会因长度越界(BKEN 的 config.h 里
                     MBEDTLS_PSK_MAX_LEN 被注释掉, 默认上限 32 字节, 而 env 里存的是
                     64 个 hex 字符 = 64)返回 0x7100 BAD_INPUT_DATA, 连接必败。
                     ESP-AT 的模型也是"按 link 显式配置", 不是全局隐式继承。*/
    #ifndef AUTH_WITH_NOTLS
    if (pATNetwork->type == NETWORK_TLS || pATNetwork->type == NETWORK_DTLS)
    {
        pATNetwork->ssl_connect_params.auth_mode  = atsvr_get_ssl_auth_mode();
        pATNetwork->ssl_connect_params.timeout_ms = 10000;
        pATNetwork->ssl_connect_params.ca_crt     = NULL;
        pATNetwork->ssl_connect_params.ca_crt_len = 0;

        memset(&pATNetwork->ssl_connect_params.psk_id, 0,
               sizeof(pATNetwork->ssl_connect_params.psk_id));
        pATNetwork->ssl_connect_params.psk        = NULL;
        pATNetwork->ssl_connect_params.psk_length = 0;
    }
#endif /* AUTH_WITH_NOTLS */

    strcpy(pATNetwork->localip,msg.localip);
    pATNetwork->localport = msg.localport;
    if(judge_the_string_is_ipv4_string(pATNetwork->localip)!=0)
    {
        if(g_env_param.wifimode.mode == 0x02)
        {
            wlan_get_ap_localip(pATNetwork->localip);
        }
        else
        {
            wlan_get_sta_localip(pATNetwork->localip);
        }
    }

    if(msg.linktype == 1 && (judge_the_string_is_ipv4_string(pATNetwork->localip)==0))
    {
        pATNetwork->is_server = 1;
    }

    ATSVRLOG("setup_msg_network host %s,port:%d \r\n",pATNetwork->host,pATNetwork->port);
}

static void network_datarev_thread( beken_thread_arg_t data )
{
    #define REV_NETWORK_DATA_LEN    2048
    int ret = 0;
    unsigned char revbuf[REV_NETWORK_DATA_LEN];
    int timeout = 1000;
    size_t readlen;
    int linkid = *(int*)data;
    /* 修复#13: 记住本线程的"世代"。链路被 CIPCLOSE 后立即 CIPSTART 时
       threadrunflag 会被重新置 TRUE, 旧线程靠 flag 判断会复活; 靠 epoch
       判断则会在当前 select(≤1s) 超时后干净退出, 且退出时不 disconnect
       (socket 已属新线程)。 */
    unsigned int my_epoch = at_network_mg[linkid].rx_epoch;
    //int linkid = (int)threadpara->data;
    ATSVRLOG("enter link %d rev thread\r\n",linkid);

    while ( at_network_mg[linkid].threadrunflag == TRUE
            && at_network_mg[linkid].rx_epoch == my_epoch){
        if(at_network_mg[linkid].is_connected(&at_network_mg[linkid]) > 0){
            memset(revbuf,0,REV_NETWORK_DATA_LEN);
            if(at_network_mg[linkid].is_server){
                if(at_network_mg[linkid].type == NETWORK_TCP ||  at_network_mg[linkid].type == NETWORK_TLS){
                    struct sockaddr_in client_addr;
                    socklen_t sockaddr_t_size = sizeof(client_addr);
                    char client_ip_str[16];
                    int tcp_listen_fd = at_network_mg[linkid].handle - LWIP_SOCKET_FD_SHIFT, client_fd = -1;
                    fd_set readfds;
                    struct timeval sel_tv;
                    FD_ZERO( &readfds );
                    FD_SET( tcp_listen_fd, &readfds );
                    /* 带超时的 select: network_stop_thread 只清运行标志,
                       若无限阻塞, 线程永远醒不来, socket 关不掉 (CIPSERVER=0 失效) */
                    sel_tv.tv_sec = 0;
                    sel_tv.tv_usec = 500 * 1000;
                    select( tcp_listen_fd + 1, &readfds, NULL, NULL, &sel_tv);
                    if(FD_ISSET( tcp_listen_fd, &readfds)){
                        client_fd = accept( tcp_listen_fd, (struct sockaddr *) &client_addr, &sockaddr_t_size );
                        if(client_fd >= 0){
                            strcpy( client_ip_str, inet_ntoa( client_addr.sin_addr ) );
                            os_printf("tcp client %s:%d connected, fd: %d", client_ip_str, client_addr.sin_port, client_fd);
                            int linkid_client = network_get_idle_linkid();
                            if(linkid_client != UNKNOW_LINK_IDX){
                                /* ESP-AT: 服务端 accept 到新连接时上报 <link id>,CONNECT */
                                {
                                    char connbuf[24];
                                    int n = snprintf(connbuf, sizeof(connbuf), "%d,CONNECT\r\n", linkid_client);
                                    atsvr_output_msg(connbuf, n);
                                }
                                at_network_mg[linkid_client].handle = client_fd + LWIP_SOCKET_FD_SHIFT;
                                pm_socket_info_t rcvmsg;
                                rcvmsg.linkid = linkid_client;
                                rcvmsg.type = NETWORK_TCP;
                                strcpy(rcvmsg.remoteip, client_ip_str);
                                rcvmsg.port = client_addr.sin_port;
                                //rcvmsg.localport = param2;
                                rcvmsg.linktype = 2;
                                rcvmsg.localip[0] = '\0';
                                rtos_push_to_queue(&network_msg_que, &rcvmsg, BEKEN_NO_WAIT);
                            }else{
                                close(client_fd);
                            }
                        }
                    }
                } else if(at_network_mg[linkid].type == NETWORK_UDP ||  at_network_mg[linkid].type == NETWORK_DTLS){
                    fd_set readfds;
                    int udp_listen_fd = at_network_mg[linkid].handle - LWIP_SOCKET_FD_SHIFT;
                    struct sockaddr_in client_addr;
                    socklen_t client_addr_len = sizeof(client_addr);
                    struct timeval sel_tv;
                    FD_ZERO( &readfds );
                    FD_SET( udp_listen_fd, &readfds );
                    /* 同 TCP server: 带超时, 让线程能检查 threadrunflag */
                    sel_tv.tv_sec = 0;
                    sel_tv.tv_usec = 500 * 1000;
                    select( udp_listen_fd + 1, &readfds, NULL, NULL, &sel_tv);
                    if ( FD_ISSET( udp_listen_fd, &readfds ) )
                    {
                        if ( FD_ISSET( udp_listen_fd, &readfds ) ) /*one client has data*/
                        {
                            readlen = recvfrom( udp_listen_fd, revbuf, 1024, 0 , (struct sockaddr *) &client_addr, &client_addr_len);
                            //show_udp_recv(revbuf, len);
                            if(readlen > 0)
                            {
                                /* ESP-AT 行为: 收到 UDP 报文时
                                   1) 记住最近对端, 让 AT+CIPSEND=<id>,<len> 能回复它
                                   2) 以 +IPD 前缀上报数据, 而不是原样回显 */
                                char *rip = inet_ntoa(client_addr.sin_addr);
                                if (rip)
                                {
                                    strncpy(at_network_mg[linkid].host, rip,
                                            sizeof(at_network_mg[linkid].host) - 1);
                                    at_network_mg[linkid].host[sizeof(at_network_mg[linkid].host) - 1] = '\0';
                                }
                                at_network_mg[linkid].port = ntohs(client_addr.sin_port);
                                {
                                    int n;
                                    char headbuf[48];
                                    /* ESP-AT 透传模式: 收到的数据裸输出, 不加 +IPD 前缀 */
                                    if (g_atsvr_status.network_transfer_mode != ATSVR_PASSTHROUGH_MODE)
                                    {
                                        if (atsvr_get_conmode())
                                            n = snprintf(headbuf, sizeof(headbuf), "+IPD,%d,%d:", linkid, (int)readlen);
                                        else
                                            n = snprintf(headbuf, sizeof(headbuf), "+IPD,%d:", (int)readlen);
                                        atsvr_output_msg(headbuf, n);
                                    }
                                    atsvr_output_msg((char *)revbuf, readlen);
                                }
                            }
                        }
                    }
                }
            } else if((ret = at_network_mg[linkid].netread(&at_network_mg[linkid],revbuf,REV_NETWORK_DATA_LEN,timeout,&readlen)) == ATSVR_RET_SUCCESS){
                int n = 0;
                char resultbuf[48];
                /* ESP-AT 接收数据格式:
                     CIPMUX=0: +IPD,<len>:
                     CIPMUX=1: +IPD,<link id>,<len>:
                   原厂这里被 CFG_SUPPORT_ESP8266 裁掉了前缀, 只吐裸数据。
                   透传模式下 ESP-AT 不加前缀, 裸输出。 */
                if (g_atsvr_status.network_transfer_mode != ATSVR_PASSTHROUGH_MODE)
                {
                    if (atsvr_get_conmode())
                        n = snprintf(resultbuf,sizeof(resultbuf),"+IPD,%d,%d:",linkid,(int)readlen);
                    else
                        n = snprintf(resultbuf,sizeof(resultbuf),"+IPD,%d:",(int)readlen);
                    atsvr_output_msg((char *)resultbuf,n);
                }
                atsvr_output_msg((char *)revbuf,readlen);
            }
            else if(at_network_mg[linkid].type == NETWORK_TCP ||  at_network_mg[linkid].type == NETWORK_TLS){
                if(ret == ATSVR_ERR_TCP_READ_FAIL || ret == ATSVR_ERR_TCP_PEER_SHUTDOWN ||  ret == ATSVR_ERR_SSL_READ){
                    at_network_mg[linkid].disconnect(&at_network_mg[linkid]);
                    at_network_mg[linkid].handle = 0;
                    /* ESP-AT: 对端断开时上报 CLOSED 事件并释放链路。
                       原厂这里不断开、回到循环顶部反复 netconnect 重连,
                       每次失败还输出 ERROR 干扰上位机解析。 */
                    {
                        char closebuf[24];
                        int n;
                        if (atsvr_get_conmode())
                            n = snprintf(closebuf, sizeof(closebuf), "%d,CLOSED\r\n", linkid);
                        else
                            n = snprintf(closebuf, sizeof(closebuf), "CLOSED\r\n");
                        atsvr_output_msg(closebuf, n);
                    }
                    goto end;
                }
            }
        }else{
            at_network_mg[linkid].netconnect(&at_network_mg[linkid]);
            if(at_network_mg[linkid].is_connected(&at_network_mg[linkid]) > 0){
                struct sockaddr_in loc_addr;
                socklen_t len =sizeof(loc_addr);
                memset(&loc_addr,0,len);
                if(getsockname(at_network_mg[linkid].handle,(struct sockaddr *)&loc_addr,&len)==0){
                    at_network_mg[linkid].localport = ntohs(loc_addr.sin_port);
                }
                if(at_network_mg[linkid].type == NETWORK_TCP ||  at_network_mg[linkid].type == NETWORK_TLS){
                    network_set_keep_alive(at_network_mg[linkid].handle,at_network_mg[linkid].keepalive);
                    if(at_network_mg[linkid].is_server){
                        listen(at_network_mg[linkid].handle - LWIP_SOCKET_FD_SHIFT, 0);
                        atsvr_cmd_rsp_ok();
                        continue;
                    }
                }
                /* ESP-AT: TCP/TLS 客户端建连成功先输出 CONNECT 事件再回 OK
                   (UDP 无连接概念, 只回 OK) */
                if(at_network_mg[linkid].type == NETWORK_TCP ||  at_network_mg[linkid].type == NETWORK_TLS){
                    char connbuf[24];
                    int n;
                    if (atsvr_get_conmode())
                        n = snprintf(connbuf, sizeof(connbuf), "%d,CONNECT\r\n", linkid);
                    else
                        n = snprintf(connbuf, sizeof(connbuf), "CONNECT\r\n");
                    atsvr_output_msg(connbuf, n);
                }
                if(g_atsvr_status.network_transfer_mode != ATSVR_PASSTHROUGH_MODE){
                    atsvr_cmd_rsp_ok();
                }
            }else{
                if(g_atsvr_status.network_transfer_mode != ATSVR_PASSTHROUGH_MODE){
                    atsvr_cmd_rsp_error();
                    goto end;
                }
            }
            rtos_thread_msleep(200);
        }
    }

    if(at_network_mg[linkid].handle && at_network_mg[linkid].rx_epoch == my_epoch){
        at_network_mg[linkid].disconnect((ATNetwork *)&at_network_mg[linkid]);
        ATSVRLOG("\r\n network_datarev_thread(NET_LINK%d) exit \r\n",linkid);
        at_network_mg[linkid].handle = 0;
    }

end:
    network_thread_slot_release();
    rtos_delete_thread(NULL);
}

static void network_msg_thread( beken_thread_arg_t data )
{
    rtos_delay_milliseconds( 1000 );
    UINT32 msg_timeout_ms = BEKEN_WAIT_FOREVER;
    int ret;
    pm_socket_info_t msg;
    char threadname[64];

    while (1)
    {
        ret = rtos_pop_from_queue(&network_msg_que, &msg, msg_timeout_ms);

        if(kNoErr == ret)
        {
            uintptr_t handle_temp = at_network_mg[msg.linkid].handle;
            ATSVRLOG("rev: msg.type:%d,linkid:%d\r\n",msg.type,msg.linkid);
            setup_msg_network(&at_network_mg[msg.linkid],msg);
            interace_network_init(&at_network_mg[msg.linkid]);
            if(msg.linktype == 2){
                at_network_mg[msg.linkid].handle = handle_temp;
            }else{
                /* 修复#13(UDP RX 死): CIPCLOSE 只清 threadrunflag, 旧接收线程
                   可能还卡在 ≤1s 的 select 里; 上位机立即 CIPSTART 同一 linkid
                   时, 若不处理会出现:
                   a) 旧线程复活(threadrunflag 被重新置 TRUE), 双线程并发
                      netconnect → 同一本地端口二次 bind 失败 → socket 泄漏,
                      接收路径乱死(实测 echo 丢、ICMP 也丢, ~20s 后才自愈);
                   b) 旧 socket 没人关, fd 泄漏。
                   这里在新建前: 先把残留旧 socket 关掉(TCP/UDP 的 disconnect
                   都只是 close(fd), 跨类型安全), 再 rx_epoch++ 让旧线程在
                   下一次循环检查时退出且不再触碰本链路。 */
                if (handle_temp) {
                    at_network_mg[msg.linkid].handle = handle_temp;
                    at_network_mg[msg.linkid].disconnect(&at_network_mg[msg.linkid]);
                }
            }
            sprintf(threadname,"NET_LINK%d",msg.linkid);
            at_network_mg[msg.linkid].rx_epoch++;
            at_network_mg[msg.linkid].threadrunflag = TRUE;
            network_creat_thread(network_datarev_thread,&msg.linkid,threadname);

            #if 0
            switch (msg.type)
            {
                case NETWORK_TCP:
                    network_creat_thread(network_tcp_datarev_thread,msg.linkid,threadname);
                    break;

                case NETWORK_UDP:
                    network_creat_thread(network_udp_datarev_thread,msg.linkid,threadname);
                    break;

                case NETWORK_TLS:
                    network_creat_thread(network_tls_datarev_thread,msg.linkid,threadname);
                    break;

                case NETWORK_DTLS:
                    break;

                default:
                    break;
            }
            #endif
        }else{
            goto exit;
        }
    }

exit:
    if(network_msg_que)
    {
        rtos_deinit_queue(&network_msg_que);
    }
    rtos_delete_thread( NULL );
}

int create_network_task()
{
    memset(g_thread_manage,0,sizeof(g_thread_manage));

    int ret = rtos_init_queue(&network_msg_que,
                            "network_queue",
                            sizeof(pm_socket_info_t),
                            MAX_ITEM_COUNT);

    if (kNoErr != ret){
        ATSVRLOG("atsvr_network_task_init ceate queue failed\r\n");
        return kGeneralErr;
    }

    rtos_create_thread(NULL,
                        THD_APPLICATION_PRIORITY,
                        "net_task",
                        (beken_thread_function_t)network_msg_thread,
                        4096,
                        (beken_thread_arg_t)0);

    /*rtos_create_thread(NULL,
    THD_APPLICATION_PRIORITY,
    "net_rev",
    (beken_thread_function_t)network_datarev_thread,
    4096,
    (beken_thread_arg_t)0);*/

    return kNoErr;
}
#endif
