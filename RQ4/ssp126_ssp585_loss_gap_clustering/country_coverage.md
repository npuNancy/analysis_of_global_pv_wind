# RQ4 国家/区域覆盖与相对损失率样本

## 1. 区域全集

空间网格目录定义了28个分析区域：

```text
Australia, Austria, Brazil, Chile, China, Denmark, Egypt, France,
Germany, Greece, India, Ireland, Italy, Japan, México, NAM-12,
Netherlands, Poland, Portugal, Romania, South-Africa, South-Korea,
Spain, Sweden, Turkey, Ukraine, United-Kingdom, Vietnam
```

其中 `NAM-12` 是北美 CORDEX 区域，不是国家；`China` 是国家区域。当前 RQ3 的 `generation_loss_region.csv` 实际包含26个区域：

```text
Australia, Austria, Brazil, Chile, Denmark, Egypt, France, Germany,
Greece, India, Ireland, Italy, Japan, México, Netherlands, Poland,
Portugal, Romania, South-Africa, South-Korea, Spain, Sweden, Turkey,
Ukraine, United-Kingdom, Vietnam
```

因此，China 和 NAM-12 不是因为相对损失率分母无效而被 RQ4 排除，而是当前损失输入表没有这两个区域的记录。

## 2. RQ4 的完整样本判定

某个区域进入某一项“技术—指标”聚类，需要同时满足：

1. 风电或光伏数据存在；
2. SSP126 和 SSP585 均有数据；
3. 2030s、2040s、2050s 三个年代均有完整10年记录；
4. 相对损失率的正常发电量分母大于0且结果有限。

因此，某个区域有部分年代数据，并不等于可以进入该次曲线聚类。当前实现不对缺失年代填零，也不对缺失国家插值。

## 3. 风电相对损失率

保留18个区域：

```text
Australia, Brazil, Chile, Egypt, France, Germany, India, Italy,
Japan, México, Poland, Portugal, Romania, South-Africa, Spain,
Turkey, Ukraine, United-Kingdom
```

排除情况如下：

| 区域 | 排除原因 |
|---|---|
| Austria | SSP126 的2030s、2040s缺少完整记录；SSP585的2030s、2040s、2050s缺少完整记录 |
| Denmark | SSP585的2030s缺少完整记录 |
| Greece | SSP126的2030s缺少完整记录 |
| Ireland | SSP585的2030s、2040s缺少完整记录 |
| Netherlands | SSP126的2030s缺少完整记录 |
| South-Korea | SSP126的2030s缺少完整记录 |
| Vietnam | SSP585的2030s缺少完整记录 |
| Sweden | SSP126三个年代的正常发电量分母均不大于0，无法计算有限的相对损失率 |
| China | 当前 RQ3 损失输入表无区域记录 |
| NAM-12 | 当前 RQ3 损失输入表无区域记录 |

因此风电相对损失率的样本数为 (28-10=18)。

## 4. 光伏相对损失率

保留9个区域：

```text
Australia, Brazil, Chile, Egypt, France, Germany, México, Spain,
United-Kingdom
```

排除情况如下：

| 区域 | 排除原因 |
|---|---|
| Austria | SSP585的2030s、2040s缺少完整记录 |
| Denmark | SSP585三个年代均缺少完整记录 |
| Greece | SSP126和SSP585三个年代均缺少完整记录 |
| India | SSP585的2030s、2040s缺少完整记录 |
| Ireland | SSP126的2030s，以及SSP585三个年代缺少完整记录 |
| Italy | SSP126和SSP585的2030s缺少完整记录 |
| Japan | SSP126和SSP585三个年代均缺少完整记录 |
| Netherlands | SSP585的2030s缺少完整记录 |
| Poland | SSP585三个年代均缺少完整记录 |
| Portugal | SSP126的2030s、2040s缺少完整记录 |
| Romania | SSP585三个年代均缺少完整记录 |
| South-Africa | SSP585三个年代均缺少完整记录 |
| South-Korea | SSP126和SSP585三个年代均缺少完整记录 |
| Sweden | SSP126的2030s、2040s缺少完整记录；SSP126的2050s正常发电量分母不大于0；SSP585三个年代均缺少完整记录 |
| Turkey | SSP585三个年代均缺少完整记录 |
| Ukraine | SSP585三个年代均缺少完整记录 |
| Vietnam | SSP585的2030s缺少完整记录 |
| China | 当前 RQ3 损失输入表无区域记录 |
| NAM-12 | 当前 RQ3 损失输入表无区域记录 |

因此光伏相对损失率的样本数为 (28-19=9)。

## 5. 如何理解两个数量

这里的18和9是“具有完整 SSP126–SSP585 三年代相对损失率曲线”的区域数，不是全球所有区域的数量，也不是聚类算法产生的数量。不同指标的分母不同，完整样本集合可以不同；同一指标下改变 Ward 的类别数 (k) 不应改变有效区域总数。

