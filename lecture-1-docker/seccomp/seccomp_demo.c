#include <string.h>
#include <errno.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <unistd.h>
#include <seccomp.h>

int main(void) {
    long before = syscall(SYS_getpid);
    printf("Before seccomp: getpid() = %ld\n", before);

    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    if (ctx == NULL) {
        fprintf(stderr, "seccomp_init failed\n");
        return 1;
    }

    int rc = seccomp_rule_add(
        ctx,
        SCMP_ACT_ERRNO(EPERM),
        SCMP_SYS(getpid),
        0
    );

    if (rc < 0) {
        fprintf(stderr, "seccomp_rule_add failed: %d\n", rc);
        seccomp_release(ctx);
        return 1;
    }

    rc = seccomp_load(ctx);
    if (rc < 0) {
        fprintf(stderr, "seccomp_load failed: %d\n", rc);
        seccomp_release(ctx);
        return 1;
    }

    errno = 0;
    long after = syscall(SYS_getpid);

    printf("After seccomp: getpid() = %ld\n", after);
    printf("errno = %d (%s)\n", errno, strerror(errno));

    seccomp_release(ctx);
    return 0;
}
