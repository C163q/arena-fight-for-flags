use std::collections::VecDeque;

pub const NONE: usize = usize::MAX;
pub const FAR: u16 = 30000;
const CACHE_ROWS: usize = 96;

pub struct Board {
    pub w: usize,
    pub n: usize,
    pub walls: Vec<u8>,
    pub adj: Vec<[usize; 4]>,
    sight: Vec<u128>,
    rows: Vec<Option<Vec<u16>>>,
    order: VecDeque<usize>,
}
impl Board {
    pub fn new(w: usize, h: usize, walls: &[u8]) -> Self {
        let n=w*h;
        let mut b=Self{w,n,walls:walls.to_vec(),adj:vec![[NONE;4];n],sight:vec![0;n],rows:vec![None;n],order:VecDeque::new()};
        for a in 0..n {
            if walls[a]!=0 {continue;}
            let x=(a%w) as i32;let y=(a/w) as i32;
            for (d,(dx,dy)) in [(0,-1),(0,1),(-1,0),(1,0)].into_iter().enumerate() {
                if let Some(p)=b.cell(x+dx,y+dy) { b.adj[a][d]=p; }
            }
            for dy in -5i32..=5 {for dx in -5i32..=5 {
                if dx.abs()+dy.abs()>5 || dx==0 && dy==0 {continue;}
                if let Some(p)=b.cell(x+dx,y+dy) {if b.trace(a,p) {b.sight[a]|=1u128<<((dy+5)*11+dx+5);}}
            }}
        }
        b
    }
    pub fn cell(&self,x:i32,y:i32)->Option<usize>{
        if x<0 || y<0 || x>=self.w as i32 || y>= (self.n/self.w) as i32 {return None;}
        let p=y as usize*self.w+x as usize;(self.walls[p]==0).then_some(p)
    }
    fn trace(&self,a:usize,b:usize)->bool {
        let mut x=(a%self.w) as i32;let mut y=(a/self.w) as i32;
        let tx=(b%self.w) as i32;let ty=(b/self.w) as i32;
        let dx=(tx-x).abs();let dy=(ty-y).abs();let sx=(tx-x).signum();let sy=(ty-y).signum();
        let mut ix=0;let mut iy=0;
        while ix<dx || iy<dy {
            let lhs=(2*ix+1)*dy;let rhs=(2*iy+1)*dx;
            if lhs==rhs {
                if self.cell(x+sx,y).is_none() || self.cell(x,y+sy).is_none(){return false;}
                x+=sx;y+=sy;ix+=1;iy+=1;
            }else if lhs<rhs{x+=sx;ix+=1;}else{y+=sy;iy+=1;}
            if self.cell(x,y).is_none(){return false;}
        }
        true
    }
    pub fn sight(&self,a:usize,b:usize)->bool {
        if a>=self.n || b>=self.n || a==b{return false;}
        let dx=(b%self.w) as i32-(a%self.w) as i32;
        let dy=(b/self.w) as i32-(a/self.w) as i32;
        dx.abs()+dy.abs()<=5 && self.sight[a] & (1u128<<((dy+5)*11+dx+5))!=0
    }
    pub fn bfs(&self,goals:&[usize])->Vec<u16>{
        let mut row=vec![FAR;self.n];let mut queue=Vec::with_capacity(self.n);
        for &p in goals {if p<self.n && self.walls[p]==0 && row[p]!=0 {row[p]=0;queue.push(p);}}
        let mut head=0;while head<queue.len(){let p=queue[head];head+=1;let d=row[p]+1;
            for &q in &self.adj[p]{if q!=NONE && row[q]==FAR{row[q]=d;queue.push(q);}}
        }row
    }
    pub fn ensure(&mut self,goal:usize){
        if goal>=self.n || self.rows[goal].is_some(){return;}
        if self.order.len()==CACHE_ROWS {let old=self.order.pop_front().unwrap();self.rows[old]=None;}
        self.rows[goal]=Some(self.bfs(&[goal]));self.order.push_back(goal);
    }
    pub fn distance(&self,a:usize,b:usize)->u16{
        if a>=self.n || b>=self.n{return FAR;}
        if let Some(row)=&self.rows[a]{return row[b];}
        if let Some(row)=&self.rows[b]{return row[a];}
        // A bounded lower bound when transient rollout positions have no cached row.
        ((a%self.w).abs_diff(b%self.w)+(a/self.w).abs_diff(b/self.w)) as u16
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn corner_touch_blocks_and_units_do_not_block() {
        let mut walls = vec![0; 81];
        walls[4 * 9 + 4] = 1;
        let board = Board::new(9, 9, &walls);
        assert!(!board.sight(4 * 9 + 5, 5 * 9 + 4));
        assert!(board.sight(2 * 9 + 2, 2 * 9 + 7));
        assert!(!board.sight(2 * 9 + 1, 2 * 9 + 7));
        assert!(!board.sight(20, 20));
    }
    #[test]
    fn shortest_path_goes_around_a_wall() {
        let mut walls = vec![0; 81];
        walls[4 * 9 + 4] = 1;
        let mut board = Board::new(9, 9, &walls);
        board.ensure(4 * 9 + 3);
        assert_eq!(board.distance(4 * 9 + 3, 4 * 9 + 5), 4);
    }
}
