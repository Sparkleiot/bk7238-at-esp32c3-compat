/*
* Tencent is pleased to support the open source community by making IoT Hub
available.
* Copyright (C) 2016 THL A29 Limited, a Tencent company. All rights reserved.

* Licensed under the MIT License (the "License"); you may not use this file
except in
* compliance with the License. You may obtain a copy of the License at
* http://opensource.org/licenses/MIT

* Unless required by applicable law or agreed to in writing, software
distributed under the License is
* distributed on an "AS IS" basis, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND,
* either express or implied. See the License for the specific language
governing permissions and
* limitations under the License.
*
*/

#ifdef __cplusplus
extern "C" {
#endif


#ifndef AUTH_WITH_NOTLS

#include <errno.h>
#include <stdint.h>
#include <string.h>

#include "mbedtls/ctr_drbg.h"
#include "mbedtls/debug.h"
#include "mbedtls/entropy.h"
#include "mbedtls/error.h"
#include "mbedtls/net_sockets.h"
#include "mbedtls/ssl.h"
#include "atsvr_error.h"
#include "atsvr_comm.h"
#include "network_interface.h"
#include "_at_svr_opts.h"
#include "atsvr_param_check.h"


#ifndef AUTH_MODE_CERT
static const int ciphersuites[] = {MBEDTLS_TLS_PSK_WITH_AES_128_CBC_SHA, MBEDTLS_TLS_PSK_WITH_AES_256_CBC_SHA, 0};
#endif

extern int net_set_block(int fd);
extern int mbedtls_ssl_conf_psk( mbedtls_ssl_config *conf,const unsigned char *psk, size_t psk_len,const unsigned char *psk_identity, size_t psk_identity_len);

/**
 * @brief data structure for mbedtls SSL connection
 */
typedef struct {
    mbedtls_net_context      socket_fd;
    mbedtls_entropy_context  entropy;
    mbedtls_ctr_drbg_context ctr_drbg;
    mbedtls_ssl_context      ssl;
    mbedtls_ssl_config       ssl_conf;
    mbedtls_x509_crt         ca_cert;
    mbedtls_x509_crt         client_cert;
    mbedtls_pk_context       private_key;
} TLSDataParams;

/**
 * @brief free memory/resources allocated by mbedtls
 */
static void _free_mebedtls(TLSDataParams *pParams)
{
    mbedtls_net_free(&(pParams->socket_fd));
    mbedtls_x509_crt_free(&(pParams->client_cert));
    mbedtls_x509_crt_free(&(pParams->ca_cert));
    mbedtls_pk_free(&(pParams->private_key));
    mbedtls_ssl_free(&(pParams->ssl));
    mbedtls_ssl_config_free(&(pParams->ssl_conf));
    mbedtls_ctr_drbg_free(&(pParams->ctr_drbg));
    mbedtls_entropy_free(&(pParams->entropy));

    at_free(pParams);
}

#if defined(MBEDTLS_DEBUG_C)
#define DEBUG_LEVEL 0
static void _ssl_debug(void *ctx, int level, const char *file, int line, const char *str)
{
    bk_printf("[mbedTLS]:[%s]:[%d]: %s\r\n", STRING_PTR_PRINT_SANITY_CHECK(file), line, STRING_PTR_PRINT_SANITY_CHECK(str));
}

#endif

/**
 * @brief mbedtls SSL client init
 *
 * 1. call a series of mbedtls init functions
 * 2. init and set seed for random functions
 * 3. load CA file, cert files or PSK
 *
 * @param pDataParams       mbedtls TLS parmaters
 * @param pConnectParams    device info for TLS connection
 * @return                  ATSVR_RET_SUCCESS when success, or err code for
 * failure
 */
static int _mbedtls_client_init(TLSDataParams *pDataParams, TLSConnectParams *pConnectParams)
{
    AT_FUNC_ENTRY;

    int ret = ATSVR_RET_SUCCESS;

    mbedtls_net_init(&(pDataParams->socket_fd));
    mbedtls_ssl_init(&(pDataParams->ssl));
    mbedtls_ssl_config_init(&(pDataParams->ssl_conf));
    mbedtls_ctr_drbg_init(&(pDataParams->ctr_drbg));
    mbedtls_x509_crt_init(&(pDataParams->ca_cert));
    mbedtls_x509_crt_init(&(pDataParams->client_cert));
    mbedtls_pk_init(&(pDataParams->private_key));

    mbedtls_entropy_init(&(pDataParams->entropy));

#if defined(MBEDTLS_DEBUG_C)
    bk_printf("_mbedtls_client_init");
    mbedtls_debug_set_threshold(DEBUG_LEVEL);
    mbedtls_ssl_conf_dbg(&pDataParams->ssl_conf, _ssl_debug, NULL);
#endif

    // custom parameter is NULL for now
    if ((ret = mbedtls_ctr_drbg_seed(&(pDataParams->ctr_drbg), mbedtls_entropy_func, &(pDataParams->entropy), NULL,
                                    0)) != 0) {
        bk_printf("mbedtls_ctr_drbg_seed failed returned 0x%04x", ret < 0 ? -ret : ret);
        return ATSVR_ERR_SSL_INIT;
    }
#if defined(MBEDTLS_X509_CRT_PARSE_C)
    if (pConnectParams->ca_crt != NULL) {
        if ((ret = mbedtls_x509_crt_parse(&(pDataParams->ca_cert), (const unsigned char *)pConnectParams->ca_crt,
                                        (pConnectParams->ca_crt_len + 1)))) {
            bk_printf("parse ca crt failed returned 0x%04x", ret < 0 ? -ret : ret);
            return ATSVR_ERR_SSL_CERT;
        }
    }
#endif

#ifdef AUTH_MODE_CERT
extern int mbedtls_x509_crt_parse_file( mbedtls_x509_crt *chain, const char *path );
extern int mbedtls_pk_parse_keyfile( mbedtls_pk_context *ctx,const char *path, const char *pwd );
    if (pConnectParams->cert_file != NULL && pConnectParams->key_file != NULL) {
        if ((ret = mbedtls_x509_crt_parse_file(&(pDataParams->client_cert), pConnectParams->cert_file)) != 0) {
            bk_printf("load client cert file failed returned 0x%x", ret < 0 ? -ret : ret);
            return ATSVR_ERR_SSL_CERT;
        }

        if ((ret = mbedtls_pk_parse_keyfile(&(pDataParams->private_key), pConnectParams->key_file, "")) != 0) {
            bk_printf("load client key file failed returned 0x%x", ret < 0 ? -ret : ret);
            return ATSVR_ERR_SSL_CERT;
        }
    } else {
        bk_printf("cert_file/key_file is empty!|cert_file=%s|key_file=%s",
            STRING_PTR_PRINT_SANITY_CHECK(pConnectParams->cert_file),
            STRING_PTR_PRINT_SANITY_CHECK(pConnectParams->key_file));
    }
#else
    bk_printf("mbedtls_ssl_conf_psk start\r\n");
    /* 原厂这里只判空, 但 mbedtls_ssl_conf_psk 还会校验 psk_len 不得超过
       MBEDTLS_PSK_MAX_LEN(BKEN 的 config.h 里该宏被注释掉 => 默认 32 字节)。
       历史上有人把 64 个 hex 字符(=32 字节的十六进制文本, strlen=64)当 PSK 存进 env,
       于是 conf_psk 直接返回 0x7100 BAD_INPUT_DATA 把整个连接打挂。
       这里显式校验并退化成"无 PSK", 让证书模式(本移植唯一支持的模式)仍可用。*/
    if (pConnectParams->psk != NULL && pConnectParams->psk_id[0] != '\0'
        && pConnectParams->psk_length > 0
        && pConnectParams->psk_length <= MBEDTLS_PSK_MAX_LEN) {

        ATSVRLOG("pConnectParams->psk:%s,pConnectParams->psk_id:%s\r\n",pConnectParams->psk,pConnectParams->psk_id);
        const char *psk_id = pConnectParams->psk_id;
        ret                = mbedtls_ssl_conf_psk(&(pDataParams->ssl_conf), (unsigned char *)pConnectParams->psk,
                                pConnectParams->psk_length, (const unsigned char *)psk_id, strlen(psk_id));
    } else {
        bk_printf("psk/pskid empty or too long (len=%d, max=%d), continue without psk\r\n",
                  (int)pConnectParams->psk_length, (int)MBEDTLS_PSK_MAX_LEN);
    }

    if (0 != ret) {
        bk_printf("mbedtls_ssl_conf_psk fail: 0x%x", ret < 0 ? -ret : ret);
        return ret;
    }
#endif

    return ATSVR_RET_SUCCESS;
}

/**
 * @brief Setup TCP connection
 *
 * @param socket_fd  socket handle
 * @param host       server address
 * @param port       server port < 0xffff;
 * @return ATSVR_RET_SUCCESS when success, or err code for failure
 */
int _mbedtls_tcp_connect(mbedtls_net_context *socket_fd, const char *host, int port)
{
    int  ret = 0;
    char port_str[6];
    snprintf(port_str, 6, "%d", port);
    ATSVRLOG("connect host:%s,port:%d\r\n",host,port);
    if ((ret = mbedtls_net_connect(socket_fd, host, port_str, MBEDTLS_NET_PROTO_TCP)) != 0) {
        ATSVRLOG("tcp connect failed returned 0x%04x errno: %d\r\n", ret < 0 ? -ret : ret, errno);
        switch (ret) {
            case MBEDTLS_ERR_NET_SOCKET_FAILED:
                return ATSVR_ERR_TCP_SOCKET_FAILED;
            case MBEDTLS_ERR_NET_UNKNOWN_HOST:
                return ATSVR_ERR_TCP_UNKNOWN_HOST;
            default:
                return ATSVR_ERR_TCP_CONNECT;
        }
    }

    if ((ret = net_set_block(socket_fd->fd)) != 0) {
        ATSVRLOG("set block faliled returned 0x%04x\r\n", ret < 0 ? -ret : ret);
        return ATSVR_ERR_TCP_CONNECT;
    }

    return ATSVR_RET_SUCCESS;
}

/**
 * @brief verify server certificate
 *
 * mbedtls has provided similar function mbedtls_x509_crt_verify_with_profile
 *
 * @return
 */
int _ATSVR_server_certificate_verify(void *hostname, mbedtls_x509_crt *crt, int depth, uint32_t *flags)
{
    return *flags;
}

uintptr_t HAL_TLS_Connect(TLSConnectParams *pConnectParams, const char *host, int port)
{
    int ret = 0;

    TLSDataParams *pDataParams = (TLSDataParams *)at_malloc(sizeof(TLSDataParams));

    if ((ret = _mbedtls_client_init(pDataParams, pConnectParams)) != ATSVR_RET_SUCCESS) {
        goto error;
    }

    bk_printf("Setting up the SSL/TLS structure...");
    if ((ret = mbedtls_ssl_config_defaults(&(pDataParams->ssl_conf), MBEDTLS_SSL_IS_CLIENT,
                                        MBEDTLS_SSL_TRANSPORT_STREAM, MBEDTLS_SSL_PRESET_DEFAULT)) != 0) {
        bk_printf("mbedtls_ssl_config_defaults failed returned 0x%04x", ret < 0 ? -ret : ret);
        goto error;
    }

    mbedtls_ssl_conf_verify(&(pDataParams->ssl_conf), _ATSVR_server_certificate_verify, (void *)host);

    /* ESP-AT 兼容修复: 原厂无条件 VERIFY_REQUIRED, 但 AT 层没有装载 CA 的命令,
       ca_cert 恒为空 => 握手必然失败(无法验证 "unknown CA")。
       对齐 ESP-AT AT+CIPSSLCCONF 的 auth_mode 语义:
         auth_mode == 0 (默认, 不认证) -> VERIFY_NONE, TLS 终于能用;
         auth_mode 2/3 (校验服务端)   -> VERIFY_REQUIRED (需要已装载 CA)。*/
    if (pConnectParams->auth_mode == 0) {
        mbedtls_ssl_conf_authmode(&(pDataParams->ssl_conf), MBEDTLS_SSL_VERIFY_NONE);
    } else {
        mbedtls_ssl_conf_authmode(&(pDataParams->ssl_conf), MBEDTLS_SSL_VERIFY_REQUIRED);
    }

    mbedtls_ssl_conf_rng(&(pDataParams->ssl_conf), mbedtls_ctr_drbg_random, &(pDataParams->ctr_drbg));

    mbedtls_ssl_conf_ca_chain(&(pDataParams->ssl_conf), &(pDataParams->ca_cert), NULL);

    /* 只有确实带了客户端证书/私钥(双向认证 auth_mode 1/3)才配置 own_cert。
       原厂无条件调用, 而 pk_context/crt 是零初始化的空上下文,
       mbedtls_ssl_conf_own_cert 会因此返回错误直接把连接打挂。*/
    if (pConnectParams->auth_mode == 1 || pConnectParams->auth_mode == 3) {
        if ((ret = mbedtls_ssl_conf_own_cert(&(pDataParams->ssl_conf), &(pDataParams->client_cert),
                                            &(pDataParams->private_key))) != 0) {
            bk_printf("mbedtls_ssl_conf_own_cert failed returned 0x%04x", ret < 0 ? -ret : ret);
            goto error;
        }
    }

    /* timeout_ms 为 0 会让 mbedtls 读到 read_timeout=0, 行为不可控; 给个兜底。*/
    mbedtls_ssl_conf_read_timeout(&(pDataParams->ssl_conf),
                                   pConnectParams->timeout_ms ? pConnectParams->timeout_ms : 10000);
    if ((ret = mbedtls_ssl_setup(&(pDataParams->ssl), &(pDataParams->ssl_conf))) != 0) {
        bk_printf("mbedtls_ssl_setup failed returned 0x%04x", ret < 0 ? -ret : ret);
        goto error;
    }

#ifndef AUTH_MODE_CERT
    // ciphersuites selection for PSK device
    if (pConnectParams->psk != NULL) {
        mbedtls_ssl_conf_ciphersuites(&(pDataParams->ssl_conf), ciphersuites);
    }
#endif

    // Set the hostname to check against the received server certificate and sni
    if ((ret = mbedtls_ssl_set_hostname(&(pDataParams->ssl), host)) != 0) {
        bk_printf("mbedtls_ssl_set_hostname failed returned 0x%04x", ret < 0 ? -ret : ret);
        goto error;
    }

    mbedtls_ssl_set_bio(&(pDataParams->ssl), &(pDataParams->socket_fd), mbedtls_net_send, mbedtls_net_recv,
                        mbedtls_net_recv_timeout);

    bk_printf("Performing the SSL/TLS handshake...");
    POINTER_SANITY_CHECK_RTN(host);
// bk_printf("Connecting to /%s/%d...", POINTER_SANITY_CHECK_RTN(host), port);
    if ((ret = _mbedtls_tcp_connect(&(pDataParams->socket_fd), host, port)) != ATSVR_RET_SUCCESS) {
        goto error;
    }

    while ((ret = mbedtls_ssl_handshake(&(pDataParams->ssl))) != 0) {
        if (ret != MBEDTLS_ERR_SSL_WANT_READ && ret != MBEDTLS_ERR_SSL_WANT_WRITE) {
            bk_printf("mbedtls_ssl_handshake failed returned 0x%04x", ret < 0 ? -ret : ret);
            if (ret == MBEDTLS_ERR_X509_CERT_VERIFY_FAILED) {
                bk_printf("Unable to verify the server's certificate");
            }
            goto error;
        }
    }

    if ((ret = mbedtls_ssl_get_verify_result(&(pDataParams->ssl))) != 0) {
        bk_printf("mbedtls_ssl_get_verify_result failed returned 0x%04x", ret < 0 ? -ret : ret);
        goto error;
    }

    mbedtls_ssl_conf_read_timeout(&(pDataParams->ssl_conf), 100);

    bk_printf("connected with /%s/%d...", STRING_PTR_PRINT_SANITY_CHECK(host), port);

    return (uintptr_t)pDataParams;

error:
    _free_mebedtls(pDataParams);
    return 0;
}

void HAL_TLS_Disconnect(uintptr_t handle)
{
    if ((uintptr_t)NULL == handle) {
        bk_printf("handle is NULL");
        return;
    }
    TLSDataParams *pParams = (TLSDataParams *)handle;
    int            ret     = 0;
    do {
        ret = mbedtls_ssl_close_notify(&(pParams->ssl));
    } while (ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE);

    mbedtls_net_free(&(pParams->socket_fd));
    mbedtls_x509_crt_free(&(pParams->client_cert));
    mbedtls_x509_crt_free(&(pParams->ca_cert));
    mbedtls_pk_free(&(pParams->private_key));
    mbedtls_ssl_free(&(pParams->ssl));
    mbedtls_ssl_config_free(&(pParams->ssl_conf));
    mbedtls_ctr_drbg_free(&(pParams->ctr_drbg));
    mbedtls_entropy_free(&(pParams->entropy));

at_free((void *)handle);
}

int HAL_TLS_Write(uintptr_t handle, unsigned char *msg, size_t totalLen, uint32_t timeout_ms, size_t *written_len)
{
    Timer timer;
    HAL_Timer_init(&timer);
    HAL_Timer_countdown_ms(&timer, (unsigned int)timeout_ms);
    size_t written_so_far;
    bool   errorFlag = false;
    int    write_rc  = 0;
    TLSDataParams *pParams = (TLSDataParams *)handle;

    for (written_so_far = 0; written_so_far < totalLen && !HAL_Timer_expired(&timer); written_so_far += write_rc) {
        while (!HAL_Timer_expired(&timer) &&
            (write_rc = mbedtls_ssl_write(&(pParams->ssl), msg + written_so_far, totalLen - written_so_far)) <= 0) {
            if (write_rc != MBEDTLS_ERR_SSL_WANT_READ && write_rc != MBEDTLS_ERR_SSL_WANT_WRITE) {
                bk_printf("HAL_TLS_write failed 0x%04x", write_rc < 0 ? -write_rc : write_rc);
                errorFlag = true;
                break;
            }
        }
        if (errorFlag) {
            break;
        }
    }
    *written_len = written_so_far;

    if (errorFlag) {
        return ATSVR_ERR_SSL_WRITE;
    } else if (HAL_Timer_expired(&timer) && written_so_far != totalLen) {
        return ATSVR_ERR_SSL_WRITE_TIMEOUT;
    }

    return ATSVR_RET_SUCCESS;
}

int HAL_TLS_Read(uintptr_t handle, unsigned char *msg, size_t totalLen, uint32_t timeout_ms, size_t *read_len)
{
    // mbedtls_ssl_conf_read_timeout(&(pParams->ssl_conf), timeout_ms); TODO:this
    // cause read blocking and no return even timeout
    // use non-blocking read
    Timer timer;
    HAL_Timer_init(&timer);
    HAL_Timer_countdown_ms(&timer, (unsigned int)timeout_ms);
    *read_len = 0;

    TLSDataParams *pParams = (TLSDataParams *)handle;

    do {
        int read_rc = 0;
        read_rc     = mbedtls_ssl_read(&(pParams->ssl), msg + *read_len, totalLen - *read_len);

        if (read_rc > 0) {
            *read_len += read_rc;
        } else if (read_rc == 0) {
            /* ESP-AT 兼容修复: 原厂把 0 当成致命错误直接 return ATSVR_ERR_SSL_READ,
               而 network_datarev_thread 见到这个值就判定"对端已关闭"并把链路拆掉
               (见 network_app.c: `ret == ATSVR_ERR_SSL_READ` -> CLOSED)。
               但 mbedtls 的 recv BIO 在**读超时**以及"暂时无数据"情形下同样返回 0
               (net_sockets.c: mbedtls_net_recv_timeout 超时返回 MBEDTLS_ERR_SSL_TIMEOUT,
                而 mbedtls_net_recv 直接返回 recv() 的值)。
               结果: TLS 链路上只要出现一小段空窗(例如握手超时兜底 10s 到期),
               空闲连接就会被误杀, 上位机莫名看到 "0,CLOSED"。
               这里把 0 当成"暂时没数据": 跳出循环, 落到下面的
               ATSVR_ERR_SSL_NOTHING_TO_READ —— RX 线程下一轮继续等, 不会误杀链路。
               真正的对端关闭会返回 MBEDTLS_ERR_SSL_CONN_EOF(负值), 仍走下面的
               致命分支, 所以不会漏掉真正的断开。*/
            break;
        } else if (read_rc != MBEDTLS_ERR_SSL_WANT_WRITE && read_rc != MBEDTLS_ERR_SSL_WANT_READ &&
                                    read_rc != MBEDTLS_ERR_SSL_TIMEOUT) {
            bk_printf("cloud_iot_network_tls_read failed: 0x%04x", read_rc < 0 ? -read_rc : read_rc);
            return ATSVR_ERR_SSL_READ;
        }

        if (HAL_Timer_expired(&timer)) {
            break;
        }

    } while (*read_len < totalLen);

    /* ESP-AT 兼容修复: 原厂要求"读满整个缓冲"才算成功
       (if (totalLen == *read_len) return ATSVR_RET_SUCCESS;),
       而 TCP 侧 hal_tcp_read_noblock 是单次 recv、读到多少交多少。
       两者语义不一致 => TLS 上一个 11 字节的回显永远填不满 REV_NETWORK_DATA_LEN,
       于是返回 ATSVR_ERR_SSL_READ_TIMEOUT, network_datarev_thread 只在
       `ret == ATSVR_RET_SUCCESS` 时吐 +IPD => **数据被静默丢弃**, 上位机永远收不到。
       这里对齐 TCP 语义: 只要读到了就成功交付, 剩下的下一轮继续读。*/
    if (*read_len > 0) {
        return ATSVR_RET_SUCCESS;
    }

    return ATSVR_ERR_SSL_NOTHING_TO_READ;
}

#ifdef __cplusplus
}
#endif

#endif
