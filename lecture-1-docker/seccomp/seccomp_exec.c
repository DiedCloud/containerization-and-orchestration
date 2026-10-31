
#include <errno.h>
#include <stdio.h>
#include <unistd.h>
#include <seccomp.h>

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s COMMAND [ARGS...]\n", argv[0]);
        return 1;
    }

    scmp_filter_ctx ctx = seccomp_init(SCMP_ACT_ALLOW);
    if (ctx == NULL) {
        fprintf(stderr, "seccomp_init failed\n");
        return 1;
    }

    int rc = seccomp_rule_add(
        ctx,
        SCMP_ACT_ERRNO(EPERM),
        SCMP_SYS(ptrace),
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

    seccomp_release(ctx);

    execvp(argv[1], &argv[1]);

    perror("execvp");
    return 1;
}
