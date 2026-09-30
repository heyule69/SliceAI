"""Entry point for the isolated, offline BandIt Plus audio worker."""
import sys
from bandit_worker import main

if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    main()