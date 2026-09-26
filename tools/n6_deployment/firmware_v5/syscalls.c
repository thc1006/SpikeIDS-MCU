/* Explicit no-I/O newlib support. No semihosting, UART, files or device calls.
 * Vendor assert/stdio attempts fail instead of reaching board peripherals. */
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <sys/stat.h>
#include "stm32n6xx.h"
#include "mailbox.h"
extern unsigned char _heap_start, _heap_end;
void *_sbrk(ptrdiff_t increment)
{
    static uintptr_t current;
    if (!current) current=(uintptr_t)&_heap_start;
    uintptr_t start=(uintptr_t)&_heap_start, end=(uintptr_t)&_heap_end;
    if ((increment > 0 && (uintptr_t)increment > end-current) ||
        (increment < 0 && (uintptr_t)(-(increment+1))+1 > current-start)) {
        errno=ENOMEM; return (void *)-1;
    }
    void *previous=(void *)current;
    if (increment >= 0) current+=(uintptr_t)increment;
    else current-=(uintptr_t)(-(increment+1))+1;
    return previous;
}
int _write(int fd,const void *data,size_t count) { (void)fd;(void)data;(void)count;errno=ENOSYS;return -1; }
int _read(int fd,void *data,size_t count) { (void)fd;(void)data;(void)count;errno=ENOSYS;return -1; }
int _close(int fd) { (void)fd;errno=EBADF;return -1; }
int _lseek(int fd,int offset,int whence) { (void)fd;(void)offset;(void)whence;errno=ENOSYS;return -1; }
int _fstat(int fd,struct stat *info) { (void)fd;(void)info;errno=ENOSYS;return -1; }
int _isatty(int fd) { (void)fd;return 0; }
int _getpid(void) { return 1; }
int _kill(int pid,int sig) { (void)pid;(void)sig;errno=ENOSYS;return -1; }
__attribute__((noreturn)) void _exit(int status)
{
    __disable_irq();g_mailbox.adapter_error=status;g_mailbox.state=V5_FAULT;__DSB();
    for (;;) __NOP();
}
