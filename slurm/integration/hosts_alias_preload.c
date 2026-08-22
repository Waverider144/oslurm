#define _GNU_SOURCE
#include <dlfcn.h>
#include <netdb.h>
#include <string.h>

static const char *alias_name(const char *name) {
    if (!name) return name;
    if (!strcmp(name, "sat001") || !strcmp(name, "sat002") ||
        !strcmp(name, "sat003") || !strcmp(name, "sat004")) {
        return "127.0.0.1";
    }
    return name;
}

int getaddrinfo(const char *node, const char *service,
                const struct addrinfo *hints, struct addrinfo **res) {
    static int (*real_getaddrinfo)(const char *, const char *,
                                   const struct addrinfo *, struct addrinfo **) = 0;
    if (!real_getaddrinfo) {
        real_getaddrinfo = dlsym(RTLD_NEXT, "getaddrinfo");
    }
    return real_getaddrinfo(alias_name(node), service, hints, res);
}

struct hostent *gethostbyname(const char *name) {
    static struct hostent *(*real_gethostbyname)(const char *) = 0;
    if (!real_gethostbyname) {
        real_gethostbyname = dlsym(RTLD_NEXT, "gethostbyname");
    }
    return real_gethostbyname(alias_name(name));
}

