"""Offline cost screen of equal Up/Down quantities in recorded public books.

Indicative near-time quote pairs, NOT simultaneous fills or executed arbitrage.
"""
import json
from pathlib import Path

from polymarket_bot.actual_research import dec
from research_fresh_data import dump,sha


def leg_cost(book,quantity,rate):
    remaining=dec(quantity); cost=dec(0)
    if remaining<=0:
        raise ValueError('Positive equal share quantity required')
    for level in sorted(book.get('asks',[]),key=lambda x:dec(x['price'])):
        price,size=dec(level['price']),dec(level['size'])
        if not 0<price<1 or size<=0:
            raise ValueError('Invalid displayed ask')
        q=min(size,remaining)
        cost+=q*(price+dec(rate)*price*(1-price))
        remaining-=q
        if remaining==0:
            return float(cost)
    raise ValueError('Insufficient displayed depth')


def main():
    output=Path('data/high_confidence_complete_sets_20261108')
    output.mkdir(parents=True,exist_ok=True)
    observations=[]; sources={}
    for folder in ('execution_probe_20261108','execution_probe_verified_20261108'):
        root=Path('data')/folder
        meta=json.loads((root/'summary.json').read_text())
        path=root/'events.jsonl'; sources[str(path)]=sha(path)
        last={}
        for line in path.open(encoding='utf-8'):
            event=json.loads(line)
            if event['kind']!='rest_book' or event['payload'].get('status')!=200:
                continue
            slug,side=event['slug'],event['side']; body=event['payload']['body']
            last[slug,side]=event
            other=last.get((slug,'down' if side=='up' else 'up'))
            if other is None:
                continue
            other_book=other['payload']['body']
            skew=abs(int(body['timestamp'])-int(other_book['timestamp']))
            receive_skew=abs(event['received_ms']-other['received_ms'])
            if skew>500 or receive_skew>750:
                continue
            try:
                rate=meta['markets'][slug]['fee']['rate']
                cost=leg_cost(body,5,rate)+leg_cost(other_book,5,rate)
            except (ValueError,KeyError):
                continue
            observations.append(dict(slug=slug,pairs_of_equal_shares=5,all_in_cost=cost,
                complete_set_collateral=5,indicative_profit_before_other_costs=5-cost,
                server_timestamp_skew_ms=skew,receive_skew_ms=receive_skew))
    report=dict(source_sha256=sources,quote_pairs=len(observations),
        unique_markets=len({r['slug'] for r in observations}),
        positive_cost_gaps=sum(r['indicative_profit_before_other_costs']>0 for r in observations),
        best_indicative_profit=max((r['indicative_profit_before_other_costs'] for r in observations),default=None),
        observations=observations,
        limitations=['Asynchronous GET quote pairs, not simultaneous executable orders; only a tiny sample of one market.',
            'Equal Up+Down is one complete set. FOK on each leg does not make both legs atomic.',
            'Cash-equivalent fee model; excludes gas/redemption/relayer costs and quote staleness race.',
            'No guarantee of acquiring or merging a complete set; no trades submitted.'])
    dump(output/'summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='observations'},indent=2))


if __name__=='__main__':
    main()
