/*
 *  Copyright (C) 2008-2015, Marvell International Ltd.
 *  All Rights Reserved.
 */

/** dhcp-server-main.c: CLI based APIs for the DHCP Server
 */
#include "sys_config.h"
#if CFG_USE_DHCPD
#include <string.h>
#include "rtos_pub.h"
#include "dhcp-priv.h"

static beken_thread_t dhcpd_thread;
static bool dhcpd_running;

/* ESP-AT compat (AT+CWDHCPS): lease range, host order. 0/0 = default
 * (AP subnet .2 ~ .101, matching ESP-AT). Survives dhcp_server_init
 * because dhcp_server_init() reads these each time. */
static uint32_t pending_range_start = 0;
static uint32_t pending_range_end = 0;

void dhcp_server_set_range(uint32_t start_host, uint32_t end_host)
{
	pending_range_start = start_host;
	pending_range_end = end_host;
}

uint32_t dhcp_server_get_pending_range_start(void) { return pending_range_start; }
uint32_t dhcp_server_get_pending_range_end(void) { return pending_range_end; }

int dhcp_server_start(void *intrfc_handle)
{
	int ret;

	dhcp_d("DHCP server start request \r\n");

	dhcp_enable_nack_dns_server();

	if (dhcpd_running || dhcp_server_init(intrfc_handle)) {
		return -1;
	}

	ret = rtos_create_thread(&dhcpd_thread,
		BEKEN_APPLICATION_PRIORITY,
		"dhcp-server",
		(beken_thread_function_t)dhcp_server,
		DHCP_SERVER_TASK_STACK_SIZE,
		0);
	if (ret) {
		dhcp_free_allocations();
		return -1;
	}

	dhcpd_running = 1;
	return 0;
}

void dhcp_server_stop(void)
{
	dhcp_d("DHCP server stop request\r\n");
	if (dhcpd_running) 
	{
		if (dhcp_send_halt() != 0) 
		{
			dhcp_w("failed to send halt to DHCP thread\r\n");
			return;
		}
		
		if (rtos_delete_thread(&dhcpd_thread) != 0)
			dhcp_w("failed to delete thread\r\n");
		dhcpd_running = 0;
	} 
	else 
	{
		dhcp_w("server not dhcpd_running.\r\n");
	}
}
#endif // CFG_USE_DHCPD
// eof

