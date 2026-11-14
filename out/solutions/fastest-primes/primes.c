// Count primes <= N (N up to 5,000,000). Odd-only Sieve of Eratosthenes.
// Reads N from stdin, prints pi(N). Original work for AIProve.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    long n;
    if (scanf("%ld", &n) != 1) return 1;
    if (n < 2) { printf("0\n"); return 0; }
    long m = (n + 1) / 2;               // odds only: index i -> 2*i+1
    unsigned char *is_comp = calloc(m, 1);
    if (!is_comp) return 1;
    for (long i = 3; i * i <= n; i += 2) {
        if (!is_comp[i / 2]) {
            for (long j = i * i; j <= n; j += 2 * i) is_comp[j / 2] = 1;
        }
    }
    long cnt = 1;                        // prime 2
    for (long i = 3; i <= n; i += 2) if (!is_comp[i / 2]) cnt++;
    printf("%ld\n", cnt);
    return 0;
}
