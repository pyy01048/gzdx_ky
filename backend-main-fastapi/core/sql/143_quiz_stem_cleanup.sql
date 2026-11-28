-- 143_quiz_stem_cleanup.sql
-- 题库清洗（2026-11-24）：去掉扫描水印/页码/章节尾注/前导点号，并隔离无法作答的残题。
-- 守卫：UPDATE 以旧题干完全相等为条件；隔离以 is_available=true 为条件（幂等）。

-- [#20770] 去水印/页码残留
UPDATE quiz_questions SET content = $q$从顺序表中删除具有最小值的元素（假设唯一）并由函数返回被删元素的值。空出的位 置由最后一个元素填补，若顺序表为空，则显示出错信息并退出运行。$q$, updated_at = now() WHERE id = 20770 AND content = $q$．从顺序表中删除具有最小值的元素（假设唯一）并由函数返回被删元素的值。空出的位 置由最后一个元素填补，若顺序表为空，则显示出错信息并退出运行。$q$;
-- [#20784] 去水印/页码残留
UPDATE quiz_questions SET content = $q$对于顺序存储的线性表，其算法时间复杂度为O(1)的运算应该是（)。 (顶尖考$q$, updated_at = now() WHERE id = 20784 AND content = $q$对于顺序存储的线性表，其算法时间复杂度为O(1)的运算应该是（)。 (顶尖考研祝您上岸）$q$;
-- [#20788] 去水印/页码残留
UPDATE quiz_questions SET content = $q$单链表中，增加一个头结点的目的是（）。$q$, updated_at = now() WHERE id = 20788 AND content = $q$．单链表中，增加一个头结点的目的是（）。 · 37·$q$;
-- [#20792] 去水印/页码残留
UPDATE quiz_questions SET content = $q$与单链表相比，双链表的优点之一是（）。$q$, updated_at = now() WHERE id = 20792 AND content = $q$．与单链表相比，双链表的优点之一是（）。$q$;
-- [#20826] 去水印/页码残留
UPDATE quiz_questions SET content = $q$栈是（）。$q$, updated_at = now() WHERE id = 20826 AND content = $q$栈是（）。 · 67 :$q$;
-- [#20860] 去水印/页码残留
UPDATE quiz_questions SET content = $q$【2016统考真题】设有如下图所示的火车车轨，入口到出口之间有n条轨道，列车的行进方向均为从左至右，列车可驶入任意一条轨道。现有编号为1～9的9列列车，驶入的次序依次是8,4,2,5,3,9,1,6,7。若期望驶出的次序依次为1～9，则n至少是（）。$q$, updated_at = now() WHERE id = 20860 AND content = $q$【2016统考真题】设有如下图所示的火车车轨，入口到出口之间有n条轨道，列车的行 进方向均为从左至右，列车可驶入任意一条轨道。现有编号为1～9的9列列车，驶入 的次序依次是8,4,2,5,3,9,1,6,7。若期望驶出的次序依次为1～9，则n至少是（）。 761935248 顶尖留耕祝您上岸） 微信公庆 Ky66 A2IB3TT$q$;
-- [#20877] 去水印/页码残留
UPDATE quiz_questions SET content = $q$对特殊矩阵采用压缩存储的主要目的是（）。$q$, updated_at = now() WHERE id = 20877 AND content = $q$．对特殊矩阵采用压缩存储的主要目的是（）。$q$;
-- [#20896] 去水印/页码残留
UPDATE quiz_questions SET content = $q$树最适合用来表示（）的数据。$q$, updated_at = now() WHERE id = 20896 AND content = $q$树最适合用来表示（）的数据。 祝您 上岸）$q$;
-- [#20933] 去水印/页码残留
UPDATE quiz_questions SET content = $q$若二叉树中结点的先序序列是.a...b，中序序列是.b..a. (顶尖考$q$, updated_at = now() WHERE id = 20933 AND content = $q$若二叉树中结点的先序序列是.a...b，中序序列是.b..a. (顶尖考研祝您上岸）$q$;
-- [#20943] 去水印/页码残留
UPDATE quiz_questions SET content = $q$在线索二叉树中，下列说法不正确的是（）。$q$, updated_at = now() WHERE id = 20943 AND content = $q$．在线索二叉树中，下列说法不正确的是（）。$q$;
-- [#20986] 去水印/页码残留
UPDATE quiz_questions SET content = $q$将下面一个由3棵树组成的森林转换为二叉树。 : 174: 树与二叉树$q$, updated_at = now() WHERE id = 20986 AND content = $q$将下面一个由3棵树组成的森林转换为二叉树。 : 174: 树与二叉树 第5章$q$;
-- [#21014] 去水印/页码残留
UPDATE quiz_questions SET content = $q$若具有n个顶点的图是一个环，则它有（）棵生成树。$q$, updated_at = now() WHERE id = 21014 AND content = $q$．若具有n个顶点的图是一个环，则它有（）棵生成树。$q$;
-- [#21038] 去水印/页码残留
UPDATE quiz_questions SET content = $q$【2021统考真题】已知无向连通图G由顶点集V和边集E组成，IE>0，当G中度为奇 数的顶点个数为不大于2的偶数时，G存在包含所有边且长度为E的路径（称为EL路 径）。设图G采用邻接矩阵存储，类型定义如下： typedef struct( //图的定义 int numVertices,numEdges; //图中实际的顶点数和边数 char VerticesList[MAxV]; //顶点表。MAXV为已定义常量 int Edge[MAXV] [MAXV]; //邻接矩阵 I MGraph; 请设计算法intIsExistEL(MGraph G），判断G是否存在EL路径，若存在，则返 回1，否则返回0。要求： ）给出算法的基本设计思想。 2）根据设计思想，采用C或C++语言描述算法，关键之处给出注释。 3）说明你所设计算法的时间复杂度和空间复杂度。$q$, updated_at = now() WHERE id = 21038 AND content = $q$【2021统考真题】已知无向连通图G由顶点集V和边集E组成，IE>0，当G中度为奇 数的顶点个数为不大于2的偶数时，G存在包含所有边且长度为E的路径（称为EL路 径）。设图G采用邻接矩阵存储，类型定义如下： typedef struct( //图的定义 int numVertices,numEdges; //图中实际的顶点数和边数 char VerticesList[MAxV]; //顶点表。MAXV为已定义常量 int Edge[MAXV] [MAXV]; //邻接矩阵 I MGraph; 请设计算法intIsExistEL(MGraph G），判断G是否存在EL路径，若存在，则返 回1，否则返回0。要求： ）给出算法的基本设计思想。 2）根据设计思想，采用C或C++语言描述算法，关键之处给出注释。 3）说明你所设计算法的时间复杂度和空间复杂度。 · 206 : 第6章图$q$;
-- [#21044] 去水印/页码残留
UPDATE quiz_questions SET content = $q$【2013统考真题】若对如下无向图进行遍历，则下列选项中，不是广度优先遍历序列的 是( )。$q$, updated_at = now() WHERE id = 21044 AND content = $q$【2013统考真题】若对如下无向图进行遍历，则下列选项中，不是广度优先遍历序列的 是( )。 (顶尖考研祝上岸)$q$;
-- [#21060] 去水印/页码残留
UPDATE quiz_questions SET content = $q$下面关于求关键路径的说法中，不正确的是（）。$q$, updated_at = now() WHERE id = 21060 AND content = $q$．下面关于求关键路径的说法中，不正确的是（）。 续时间的差$q$;
-- [#21066] 去水印/页码残留
UPDATE quiz_questions SET content = $q$【2014统考真题】对下图所示的有向图进行拓扑排序，得到的拓扑序列可能是（）。$q$, updated_at = now() WHERE id = 21066 AND content = $q$【2014统考真题】对下图所示的有向图进行拓扑排序，得到的拓扑序列可能是（）。 微信公众8 （顶尖考研裙您上岸）$q$;
-- [#21074] 去水印/页码残留
UPDATE quiz_questions SET content = $q$已知有向图如下图所示。 1）写出该图的邻接矩阵表示并据此给出从顶点1出发的深度优先遍历序列。 2）求该有向图的强连通分量的数目。 3）给出该图的任意两个拓扑序列。 4）若将该图视为无向图，分别用Prim算法和Kruskal算法求最小生成树。$q$, updated_at = now() WHERE id = 21074 AND content = $q$已知有向图如下图所示。 研祝您上岸） 1）写出该图的邻接矩阵表示并据此给出从顶点1出发的深度优先遍历序列。 2）求该有向图的强连通分量的数目。 3）给出该图的任意两个拓扑序列。 4）若将该图视为无向图，分别用Prim算法和Kruskal算法求最小生成树。$q$;
-- [#21119] 去水印/页码残留
UPDATE quiz_questions SET content = $q$下列关于二分查找的叙述中，正确的是（）。$q$, updated_at = now() WHERE id = 21119 AND content = $q$下列关于二分查找的叙述中，正确的是（）。 · 261 :$q$;
-- [#21128] 去水印/页码残留
UPDATE quiz_questions SET content = $q$【2017统考真题】下列二叉树中，可能成为折半查找判定树（不含外部结点）的是（）。$q$, updated_at = now() WHERE id = 21128 AND content = $q$【2017统考真题】下列二叉树中，可能成为折半查找判定树（不含外部结点）的是（）。 英考研祝您$q$;
-- [#21135] 去水印/页码残留
UPDATE quiz_questions SET content = $q$对于二叉排序树，下面的说法中，（）是正确的。$q$, updated_at = now() WHERE id = 21135 AND content = $q$．对于二叉排序树，下面的说法中，（）是正确的。$q$;
-- [#21138] 去水印/页码残留
UPDATE quiz_questions SET content = $q$分别以下列序列构造二叉排序树，与用其他3个序列所构造的结果不同的是（）。$q$, updated_at = now() WHERE id = 21138 AND content = $q$分别以下列序列构造二叉排序树，与用其他3个序列所构造的结果不同的是（）。 :282: 第7章查找$q$;
-- [#21142] 去水印/页码残留
UPDATE quiz_questions SET content = $q$具有5层结点的AVL至少有（）个结点。$q$, updated_at = now() WHERE id = 21142 AND content = $q$具有5层结点的AVL至少有（）个结点。 +c.15 上岸)17$q$;
-- [#21143] 去水印/页码残留
UPDATE quiz_questions SET content = $q$下列关于红黑树的说法中，不正确的是（)。$q$, updated_at = now() WHERE id = 21143 AND content = $q$．下列关于红黑树的说法中，不正确的是（)。$q$;
-- [#21146] 去水印/页码残留
UPDATE quiz_questions SET content = $q$将关键字5,4,3,2,1依次插入初始为空的红黑树T，则T的最终形态是（）。$q$, updated_at = now() WHERE id = 21146 AND content = $q$将关键字5,4,3,2,1依次插入初始为空的红黑树T，则T的最终形态是（）。 · 283:$q$;
-- [#21148] 去水印/页码残留
UPDATE quiz_questions SET content = $q$【2010统考真题】在下图所示的平衡二叉树中插入关键字48后得到一棵新平衡二叉树， 在新平衡二叉树中，关键字37所在结点的左、右子结点中保存的关键字分别是（）。$q$, updated_at = now() WHERE id = 21148 AND content = $q$【2010统考真题】在下图所示的平衡二叉树中插入关键字48后得到一棵新平衡二叉树， 在新平衡二叉树中，关键字37所在结点的左、右子结点中保存的关键字分别是（）。 （顶尖考研祝） （上岸）$q$;
-- [#21211] 去水印/页码残留
UPDATE quiz_questions SET content = $q$对n个不同的元素利用冒泡法从小到大排序，在（）情况下元素交换的次数最多。$q$, updated_at = now() WHERE id = 21211 AND content = $q$．对n个不同的元素利用冒泡法从小到大排序，在（）情况下元素交换的次数最多。$q$;
-- [#21231] 去水印/页码残留
UPDATE quiz_questions SET content = $q$设线性表中每个元素有两个数据项k和k2，现对线性表按以下规则进行排序：先看数据项ki，ki值小的元素在前，大的元素在后；在k;值相同的情况下，再看kz，k²值小的在前，大的元素在后。满足这种要求的排序方法是（）。$q$, updated_at = now() WHERE id = 21231 AND content = $q$设线性表中每个元素有两个数据项k和k2，现对线性表按以下规则进行排序：先看数据 项ki，ki值小的元素在前，大的元素在后；在k;值相同的情况下，再看kz，k²值小的在 前，大的元素在后。满足这种要求的排序方法是（）。 : 344 : 第8排序 (顶尖考研祝您上岸）$q$;

-- 隔离：无法作答的残题
-- [#210] formula_missing
UPDATE quiz_questions SET is_available = false, needs_review = true, validation_status = 'warn', validation_errors = coalesce(validation_errors, '[]'::jsonb) || $q$[{"code":"formula_missing","detail":"题干公式丢失，仅剩「函数（ ）．」，无法判断被积函数与被选项对应关系，移出练习池待补公式"}]$q$::jsonb, validated_at = now(), updated_at = now() WHERE id = 210 AND is_available = true;
-- [#319] formula_missing
UPDATE quiz_questions SET is_available = false, needs_review = true, validation_status = 'warn', validation_errors = coalesce(validation_errors, '[]'::jsonb) || $q$[{"code":"formula_missing","detail":"题干公式丢失，仅剩「极限（ ）．」，无法作答，移出练习池待补公式"}]$q$::jsonb, validated_at = now(), updated_at = now() WHERE id = 319 AND is_available = true;
-- [#320] formula_missing
UPDATE quiz_questions SET is_available = false, needs_review = true, validation_status = 'warn', validation_errors = coalesce(validation_errors, '[]'::jsonb) || $q$[{"code":"formula_missing","detail":"题干公式丢失，仅剩「极限（ ）．」，无法作答，移出练习池待补公式"}]$q$::jsonb, validated_at = now(), updated_at = now() WHERE id = 320 AND is_available = true;
-- [#321] formula_missing
UPDATE quiz_questions SET is_available = false, needs_review = true, validation_status = 'warn', validation_errors = coalesce(validation_errors, '[]'::jsonb) || $q$[{"code":"formula_missing","detail":"题干公式丢失，仅剩「极限（ ）．」，无法作答，移出练习池待补公式"}]$q$::jsonb, validated_at = now(), updated_at = now() WHERE id = 321 AND is_available = true;
-- [#21020] stem_truncated
UPDATE quiz_questions SET is_available = false, needs_review = true, validation_status = 'warn', validation_errors = coalesce(validation_errors, '[]'::jsonb) || $q$[{"code":"stem_truncated","detail":"题干末尾被扫描水印挤断（「集中到对角 线以…」），语义不完整，移出练习池待补全"}]$q$::jsonb, validated_at = now(), updated_at = now() WHERE id = 21020 AND is_available = true;
