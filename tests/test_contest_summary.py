"""Hand-counted public events, not a replica of engine settlement algorithms."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
from contest_tools_fixtures import ToolFixture
try:
    from contest_lib import summary
except ImportError:summary=None


def sample(root):
    game_map=json.loads((root.parent/'map-fixture.json').read_text())
    units=[]
    for team in range(2):
        for i in range(3):
            units.append({'id':{'team_id':team,'unit_id':i},'position':{'x':1+i if team==0 else 5+i,'y':2 if team==0 else 6},
                          'hp':3,'carrying':None,'respawn_at_turn':None})
    units[0].update(hp=1,carrying=1)
    initial={'turn':0,'scores':[0,0],'units':units,'flags':[{'id':1,'site_id':0,'location':{'state':'carried','unit':units[0]['id']}}],
             'sites':[{'site_id':0,'active_flag_id':1,'next_attempt_turn':None}],'rng_state':12345,'next_flag_id':2,'outcome':None}
    start=copy.deepcopy(initial);start['turn']=1
    end=copy.deepcopy(start);end['scores']=[1,0];end['units'][0].update(position=None,hp=0,carrying=None,respawn_at_turn=12)
    end['flags'][0]['location']={'state':'ground','position':{'x':1,'y':2}}
    end['outcome']={'winners':[0],'reason':'max_turns'}
    events=[]
    def event(kind,**data):
        e={'event_id':f't1.e{len(events)}','phase':'shoot','type':kind,**data};events.append(e)
    for i in range(3):event('shot',shooter={'team_id':1,'unit_id':i},target={'x':1,'y':2},validation='ok',result='hit',hit_unit=units[0]['id'],damage=1)
    event('hp_change',unit=units[0]['id'],before=1,after=0,damage=3,sources=['t1.e0','t1.e1','t1.e2'])
    event('death',unit=units[0]['id'],position={'x':1,'y':2},source='t1.e3',respawn_at_turn=12)
    event('carry_change',unit=units[0]['id'],before=1,after=None,reason='death_drop')
    event('carry_change',unit=units[1]['id'],before=None,after=2,reason='ground_pickup')
    event('carry_change',unit=units[1]['id'],before=None,after=3,reason='spawn_pickup')
    event('score',unit=units[1]['id'],team_id=0,before=0,after=1)
    for reason,result in [('contested','blocked'),('occupied_or_cycle','blocked'),('killed_before_move','cancelled'),('carrying_cannot_enter_flag','not_executed'),('ok','moved')]:
        event('move',unit=units[1]['id'],validation='ok' if reason!='carrying_cannot_enter_flag' else reason,result=result,reason=reason)
    # Shape-valid boundary fixture; the fake verifier is explicit about not proving engine rules.
    record={'format_version':1,'call_order':[0,1],'calls':[{'team_id':i,'turn':1,'status':'ok','elapsed_us':100+i,'init_elapsed_us':0} for i in range(2)],
            'frame':{'turn':1,'start':start,'end':end,'events':events,'requested':[[{'kind':'wait'}]*3,[{'kind':'shoot','target':{'x':1,'y':2}}]*3]}}
    root.mkdir();(root/'frames').mkdir()
    manifest={'format_version':1,'status':'complete','last_complete_turn':1,'match_id':'fixture','seed':42,
              'teams':[{'team_id':i,'name':f'team{i}'} for i in range(2)]}
    result={'complete':True,'turns':1,'scores':[1,0],'outcome':end['outcome'],'ai_failures':[0,0],'illegal_actions':[1,0]}
    for name,data in [('manifest.json',manifest),('map.json',game_map),('initial.json',{'format_version':1,'state':initial}),('summary.json',result),('frames/000001.json',record)]:
        (root/name).write_text(json.dumps(data))
    (root/'map.ron').write_text('fixture');(root/'initial.txt').write_text('fixture');(root/'frames/000001.txt').write_text('fixture')
    return record


class SummaryTests(ToolFixture):
    def setUp(self):
        super().setUp();self.match=self.base/'match';self.record=sample(self.match)
    def result(self):
        self.assertIsNotNone(summary,'summary module missing')
        return summary.summarize_match(self.match,self.runner,self.base/'logs')

    def test_public_event_metrics_and_overkill(self):
        d=self.result();a,b=d['teams']
        self.assertEqual(b['shooting']['hit'],3)
        self.assertEqual(b['shooting']['nominal_damage'],3)
        self.assertEqual(a['health']['damage_taken'],1)
        self.assertEqual((a['health']['deaths'],a['health']['carrying_deaths']),(1,1))
        self.assertEqual(a['flags'],{'ground_pickups':1,'spawn_pickups':1,'returns':1})
        self.assertEqual(a['movement']['contested'],1)
        self.assertEqual(a['movement']['occupied_or_cycle'],1)
        self.assertEqual(a['movement']['killed_before_move'],1)
        self.assertEqual(a['movement']['illegal'],1)
        self.assertEqual(a['movement']['moved'],1)
        self.assertEqual(b['shooting']['hit_rate'],1)
        self.assertNotIn('rng_state',json.dumps(d));self.assertNotIn('next_attempt_turn',json.dumps(d))

    def test_friendly_fire_and_representatives_are_bounded(self):
        self.record['frame']['events'][0]['shooter']['team_id']=0
        self.record['frame']['events']+=[copy.deepcopy(self.record['frame']['events'][0]) for _ in range(20)]
        for i,e in enumerate(self.record['frame']['events']):e['event_id']=f't1.e{i}'
        (self.match/'frames/000001.json').write_text(json.dumps(self.record))
        d=self.result();self.assertEqual(d['teams'][0]['shooting']['friendly_hits'],21)
        self.assertLessEqual(len(d['teams'][0]['examples']['shot_hit']),3)

    def test_incomplete_missing_frames_and_bad_summary_rejected(self):
        self.assertIsNotNone(summary)
        for file,field,value in [('manifest.json','status','in_progress'),('manifest.json','last_complete_turn',2),('summary.json','scores',[9,9])]:
            p=self.match/file;original=p.read_text();data=json.loads(original);data[field]=value;p.write_text(json.dumps(data))
            with self.subTest(field=field),self.assertRaises(ValueError):self.result()
            p.write_text(original)

    def test_candidate_aggregation_follows_role_across_seats(self):
        self.assertIsNotNone(summary)
        aggregate=getattr(summary,'aggregate_candidates',None)
        self.assertTrue(callable(aggregate),'candidate aggregation missing')
        from contest_lib.experiment import prepare_suite,resume_suite,suite_rows
        root=self.base/'suite'
        prepare_suite([('main',self.ai)],[self.map],self.opponent,self.runner,root)
        resume_suite(root)
        data=suite_rows(root)
        first=self.result();first.update(version_id='main',candidate_team=0)
        second=copy.deepcopy(first);second['candidate_team']=1
        result=aggregate([first,second],data)[0]
        self.assertEqual(result['matches'],2)
        self.assertEqual(result['metrics']['health']['deaths'],1)
        self.assertEqual(result['metrics']['shooting']['hit'],3)
        self.assertEqual(result['metrics']['calls'],2)
        self.assertEqual(result['score'],500)

    def test_non_object_records_fail_with_a_location(self):
        self.assertIsNotNone(summary)
        for name in ['manifest.json','initial.json','summary.json','frames/000001.json']:
            path=self.match/name;original=path.read_text();path.write_text('[]')
            with self.subTest(name=name),self.assertRaises(ValueError):self.result()
            path.write_text(original)

    def test_size_limits_and_no_overwrite(self):
        self.assertIsNotNone(summary)
        with patch.object(summary,'MAX_JSON',128):
            with self.assertRaisesRegex(ValueError,'limit'):self.result()
        out=self.base/'analysis';out.mkdir();(out/'keep').write_text('human')
        with self.assertRaises(ValueError):summary.write_summary(self.match,out,self.runner)
        self.assertEqual((out/'keep').read_text(),'human')

    def test_output_and_disk_estimate_are_readable(self):
        self.assertIsNotNone(summary)
        out=self.base/'analysis';summary.write_summary(self.match,out,self.runner,estimate_matches=10)
        d=json.loads((out/'summary.json').read_text())
        self.assertEqual(d['disk']['sample_matches'],1)
        self.assertEqual(d['disk']['estimated_matches'],10)
        self.assertEqual(d['disk']['estimated_bytes'],d['disk']['bytes']*10)
        self.assertIn('名义命中伤害',(out/'summary.md').read_text())
